"""Synthetic hospital information system: IHE PAM France ADT messages for the MCO demo.

Generates a plausible stream of movements for the demo hospital of ``seed-demo-mco``
(its UF codes, rooms and beds): emergency arrivals, admission decisions, hospitalisations
from the emergency department, programmed admissions, transfers, leaves of absence,
discharges and a few cancellations. Every identifier and name is invented.

    python -m tools.his_simulator --dry-run --count 20                 # print ER7
    python -m tools.his_simulator --url http://localhost:8110 \\
        --email agent@ch-demo.hospitalos.fr --password demo-hospitalos-2026 --rate 12

``--rate`` is in messages per minute; the movement times follow the wall clock from now.
With ``--database-url`` (read only), beds are picked among the beds free in the database,
so the demo does not collide with the patients already seeded.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx

from services.admissions_smr.seed_mco import MCO_SITE, UNITS

HL7_TYPE = "x-application/hl7-v2+er7"
ED_UF = next(u.uf_code for u in UNITS[MCO_SITE] if u.code == "urgences")
WARDS = [u for u in UNITS[MCO_SITE] if u.installed]
_FIRST = ["CAMILLE", "DOMINIQUE", "CLAUDE", "SACHA", "ALIX", "MORGAN", "LOUISON", "ANDREA"]
_LAST = ["FICTIF", "INVENTE", "EXEMPLE", "MODELE", "SPECIMEN", "TEMOIN"]


@dataclass(frozen=True)
class BedRef:
    uf: str
    room: str
    label: str
    sex: str = "X"  # X, F or M


def seed_beds() -> list[BedRef]:
    """Room and bed labels exactly as ``seed_mco._add_beds`` builds them."""
    beds = []
    for spec in WARDS:
        singles = round(spec.installed * spec.single_share)
        singles += (spec.installed - singles) % 2
        floor = spec.uf_code[:2]
        for n in range(1, singles + 1):
            beds.append(BedRef(spec.uf_code, f"{floor}{n:02d}", f"{floor}{n:02d}"))
        for n in range(singles + 1, singles + 1 + (spec.installed - singles) // 2):
            beds += [BedRef(spec.uf_code, f"{floor}{n:02d}", f"{floor}{n:02d}{s}") for s in "AB"]
    return beds


def free_beds_from_db(url: str) -> list[BedRef]:
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from services.admissions_smr.models import Bed, BedPool

    with Session(create_engine(url)) as session:
        rows = session.execute(
            select(BedPool.uf_code, Bed.room, Bed.label, Bed.sex_constraint)
            .join(BedPool, BedPool.id == Bed.pool_id)
            .where(Bed.status == "libre", Bed.active, BedPool.uf_code.is_not(None))
        ).all()
    return [BedRef(str(uf), room, label, sex) for uf, room, label, sex in rows]


@dataclass
class Patient:
    ipp: str
    nda: str
    name: str
    birth: str
    sex: str
    steps: list[str]
    bed: BedRef | None = None
    ward: str = ""  # target unit of the admission
    previous_bed: BedRef | None = None
    last_ref: str | None = None
    last_event: str | None = None


@dataclass
class Simulator:
    seed: int = 7
    start: datetime = field(default_factory=lambda: datetime.now(UTC))
    step: timedelta = timedelta(minutes=5)
    beds: list[BedRef] = field(default_factory=seed_beds)
    facility: str = "CHDR_SIM"
    active: int = 8  # patients followed at the same time

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)
        self.clock = self.start
        self.count = 0
        self.created = 0
        self.patients: list[Patient] = []
        self.free = list(self.beds)
        self.rng.shuffle(self.free)

    # --- one message --------------------------------------------------------------

    def er7(
        self,
        p: Patient,
        event: str,
        cls: str,
        location: str,
        action: str = "INSERT",
        ref: str | None = None,
        extra: str = "",
    ) -> str:
        self.count += 1
        stamp = self.clock.astimezone(UTC).strftime("%Y%m%d%H%M%S+0000")
        ref = ref or f"SIM-MVT-{self.seed}-{self.count}"
        if action == "INSERT":
            p.last_ref, p.last_event = ref, event
        pv1 = ["PV1", "", cls, location] + [""] * 15 + [f"{p.nda}^^^GAM_SIM^AN"]
        segments = [
            f"MSH|^~\\&|GAM_SIM|{self.facility}|HOSPITALOS|CHDR|{stamp}||ADT^{event}^ADT_A01|"
            f"SIM-{self.seed}-{self.count}|P|2.5^FRA^2.9|||||FRA|UNICODE UTF-8",
            f"EVN||{stamp}",
            f"PID|||{p.ipp}^^^GAM_SIM^PI||{p.name}^^^^L||{p.birth}|{p.sex}|||"
            f"1 RUE IMAGINAIRE^^DEUX-RIVIERES^^59999",
            "|".join(pv1) + extra,
            f"ZBE|{ref}^GAM_SIM|{stamp}||{action}|N",
        ]
        return "\r".join(segments) + "\r"

    def take_bed(self, uf: str, sex: str) -> BedRef | None:
        bed = next((b for b in self.free if b.uf == uf and b.sex in ("X", sex)), None)
        if bed is not None:
            self.free.remove(bed)
        return bed

    def new_patient(self) -> Patient:
        self.created += 1
        n = self.created
        sex = self.rng.choice("FM")
        birth = f"{self.rng.randint(1930, 2005)}{self.rng.randint(1, 12):02d}15"
        if self.rng.random() < 0.6:
            steps = ["A04"]
            roll = self.rng.random()
            if roll < 0.45:
                steps += ["A02_DECISION", "A06"] + (["A02"] if self.rng.random() < 0.25 else [])
                steps += ["A03"]
            elif roll < 0.5:
                steps += ["A06", "A02", "A12", "A03"]  # a transfer entered by mistake
            else:
                steps += ["A03_ED"]
        else:
            steps = ["A01"] + (["A21", "A22"] if self.rng.random() < 0.15 else []) + ["A03"]
            if self.rng.random() < 0.08:
                steps = ["A01", "A11"]
        return Patient(
            ipp=f"SIM{self.seed:02d}{n:06d}",
            nda=f"V{self.seed:02d}{n:07d}",
            name=f"{self.rng.choice(_LAST)}^{self.rng.choice(_FIRST)}",
            birth=birth,
            sex=sex,
            steps=steps,
            ward=self.rng.choice(WARDS).uf_code,
        )

    def location(self, bed: BedRef) -> str:
        return f"{bed.uf}^{bed.room}^{bed.label}"

    def advance(self, p: Patient) -> str | None:
        step = p.steps.pop(0)
        if p.previous_bed is not None and step != "A12":
            self.free.append(p.previous_bed)  # the transfer stands: the old bed is free
            p.previous_bed = None
        if step == "A04":
            return self.er7(p, "A04", "E", f"{ED_UF}^^")
        if step == "A03_ED":
            return self.er7(p, "A03", "E", f"{ED_UF}^^", extra="|" * 17 + "8")
        ward = p.ward if step != "A02" else self.rng.choice(WARDS).uf_code
        if step == "A02_DECISION":
            return self.er7(p, "A02", "E", f"{ward}^^")
        if step in ("A01", "A06", "A02"):
            bed = self.take_bed(ward, p.sex)
            if bed is None and step == "A02":
                p.steps = [s for s in p.steps if s != "A12"]  # no transfer, nothing to cancel
                return None
            if bed is None:  # hospital full: the patient goes to another hospital
                p.steps.clear()
                ed = p.last_event in ("A04", "A02")
                return self.er7(p, "A03", "E", f"{ED_UF}^^", extra="|" * 17 + "7") if ed else None
            p.previous_bed, p.bed = (p.bed if step == "A02" else None), bed
            return self.er7(p, step, "I", self.location(bed))
        assert p.bed is not None
        if step == "A12":  # the transfer was a mistake: back to the previous bed
            mistaken, p.bed, p.previous_bed = p.bed, p.previous_bed, None
            self.free.append(mistaken)
            return self.er7(p, "A12", "I", self.location(mistaken), "CANCEL", p.last_ref)
        if step == "A11":
            self.free.append(p.bed)
            return self.er7(p, "A11", "I", self.location(p.bed), "CANCEL", p.last_ref)
        if step in ("A21", "A22"):
            return self.er7(p, step, "I", self.location(p.bed))
        assert step == "A03"
        self.free.append(p.bed)
        return self.er7(p, "A03", "I", self.location(p.bed))

    def messages(self) -> Iterator[str]:
        while True:
            self.clock += self.step
            if len(self.patients) < self.active and (not self.patients or self.rng.random() < 0.4):
                self.patients.append(self.new_patient())
            patient = self.rng.choice(self.patients)
            message = self.advance(patient)
            if not patient.steps:
                self.patients.remove(patient)
            if message is not None:
                yield message


# --- command line --------------------------------------------------------------------


def post(args: argparse.Namespace, sim: Simulator) -> int:
    client = httpx.Client(base_url=args.url.rstrip("/"), timeout=30)

    def login() -> dict[str, str] | None:
        r = client.post("/api/auth/login", json={"email": args.email, "password": args.password})
        if r.status_code != 200:
            print(f"connexion refusée ({r.status_code})", file=sys.stderr)
            return None
        return {"Authorization": f"Bearer {r.json()['token']}", "Content-Type": HL7_TYPE}

    auth = login()
    if auth is None:
        return 1
    counts: dict[str, int] = {}
    for n, message in enumerate(sim.messages(), start=1):
        answer = client.post("/api/ingest/hl7", content=message.encode(), headers=auth)
        if answer.status_code == 401:  # token expired during a long-running demo
            auth = login()
            if auth is None:
                return 1
            answer = client.post("/api/ingest/hl7", content=message.encode(), headers=auth)
        msa = next((s for s in answer.text.split("\r") if s.startswith("MSA")), "MSA|??")
        code = msa.split("|")[1]
        counts[code] = counts.get(code, 0) + 1
        event = message.split("|")[8]
        print(f"{n:4d} {event:<15} {answer.status_code} {msa}")
        if args.count and n >= args.count:
            break
        time.sleep(60 / args.rate)
    print("bilan :", counts)
    return 0 if set(counts) <= {"AA"} else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="afficher les messages ER7")
    parser.add_argument("--count", type=int, default=0, help="nombre de messages (0 = infini)")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--start", type=datetime.fromisoformat, default=None)
    parser.add_argument("--url", default="http://localhost:8110")
    parser.add_argument("--email", default="agent@ch-demo.hospitalos.fr")
    parser.add_argument("--password", default="demo-hospitalos-2026")
    parser.add_argument("--rate", type=float, default=12.0, help="messages par minute")
    parser.add_argument("--database-url", default=None, help="lits libres lus en base")
    args = parser.parse_args(argv)
    if args.rate <= 0:
        parser.error("--rate doit être positif")
    sim = Simulator(
        seed=args.seed,
        start=args.start or datetime.now(UTC),
        step=timedelta(minutes=60 / args.rate) if not args.dry_run else timedelta(minutes=5),
        beds=free_beds_from_db(args.database_url) if args.database_url else seed_beds(),
    )
    if args.dry_run:
        for n, message in enumerate(sim.messages(), start=1):
            print(message.replace("\r", "\n"))
            if n >= (args.count or 20):
                break
        return 0
    return post(args, sim)


if __name__ == "__main__":
    sys.exit(main())
