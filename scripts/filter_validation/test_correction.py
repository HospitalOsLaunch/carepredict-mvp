import itertools
import unittest

from correction import W, A, choices, reconcile_placements, assert_consistent
from hospitalos.howm.world import Bed, Unit, Request


class CorrectionTests(unittest.TestCase):
    def test_all_delivery_orders_preserve_same_tick_placement(self):
        events = [
            (60, 60, "departure", "old", "A", {"bed": "b"}),
            (60, 60, "bed_dirty", "b", "A", {}),
            (60, 60, "cleaning_start", "b", "A", {}),
        ]
        for order in itertools.permutations(events):
            ps = W.PublicStreamN([])
            for event in order:
                ps._apply(event)
            self.assertEqual(ps.beds["b"].data["state"], "cleaning")
        done = (120, 120, "cleaning_done", "b", "A", {})
        placed = (120, 120, "placed", "new", "A", dict(rid="Rnew", bed="b", unit="A", acuity=1, iso=False, transport=False))
        for order in itertools.permutations([done, placed]):
            ps = W.PublicStreamN([])
            for i, event in enumerate(order):
                event = (event[0], 120 + i * 60, *event[2:])
                ps.obs.append(event)
            ps.advance(180)
            self.assertEqual(ps.beds["b"].data["state"], "occ")
            self.assertIn("new", ps.present_stays())
            # A genuinely later departure must still win.
            ps._apply((135, 190, "departure", "new", "A", {"bed": "b"}))
            self.assertEqual(ps.beds["b"].data["state"], "dirty")

    def test_future_suffix_is_invisible(self):
        visible = [(60, 60, "cleaning_start", "b", "A", {})]
        hidden = [(75, 200, "cleaning_done", "b", "A", {})]
        for observations in (visible, visible + hidden):
            ps = W.PublicStreamN(observations)
            ps.advance(199)
            self.assertEqual(ps.beds["b"].data["state"], "cleaning")

    def test_placement_conserves_patients_and_isolation(self):
        sp = W.n_unit_structure("CORRECTION_TEST", 0, 4)
        eng = W.initial_engine(sp, W.ProvN(sp, 0))
        unit = sp.units[0]
        eng.beds = {"b": Bed("b", unit, False)}
        eng.units = {unit: Unit(unit, ["b"], {}, {})}
        eng.stays, eng.queue, eng.transfer_pending = {}, {unit: []}, {}
        eng.tick = 100
        eng.queue[unit] = [Request("Riso", unit, True, 1, False, 90),
                           Request("Rplain", unit, False, 1, False, 91)]
        reconcile_placements(eng, W.ProvN(sp, 10001))
        self.assertEqual(eng.tick, 100)
        self.assertEqual(eng.beds["b"].stay, "Splain")
        self.assertEqual([r.rid for r in eng.queue[unit]], ["Riso"])
        self.assertEqual(eng.stays["Splain"].placed_tick, 99)
        assert_consistent(eng)

    def test_no_commitments_outside_followup(self):
        sp = W.n_unit_structure("CORRECTION_TEST", 0, 4)
        eng = W.initial_engine(sp, W.ProvN(sp, 0))
        start, end = 52 * 4, 76 * 4
        for tick in range(start, end, 24):
            eng.tick = tick
            acts = choices(eng, sp.units, start, end)
            self.assertEqual(acts[0]["kind"], "none")
            for act in acts:
                self.assertLessEqual(act["end"], end)
                self.assertTrue(A.admissible(eng, act, sp.n, start))

    def test_transport_done_before_start_does_not_restart_service(self):
        sp = W.n_unit_structure("CORRECTION_TEST", 0, 4)
        eng = W.initial_engine(sp, W.ProvN(sp, 0))
        st = next(iter(eng.stays.values()))
        obs = W.static_obs(eng, sp)
        obs.append((60, 60, "transport_done", st.sid, st.unit, {}))
        ps = W.PublicStreamN(obs)
        ps.advance(89)
        pe = ps.to_engine_n(6)
        s = pe.stays[st.sid]
        self.assertTrue(s.ready and s.authorised and s.tr_accepted)
        self.assertNotIn(st.sid, pe.tr_service)
        self.assertEqual(s.tr_end, 4)

    def test_guard_retains_declared_transport_even_for_old_service(self):
        from guarded_filter import posterior, DeclaredService
        from service_filter import ServiceLaw
        sp = W.n_unit_structure("CORRECTION_TEST", 0, 4)
        eng = W.initial_engine(sp, W.ProvN(sp, 0))
        st = next(iter(eng.stays.values()))
        obs = W.static_obs(eng, sp)
        obs.append((60, 60, "transport_start", st.sid, st.unit, {}))
        ps = W.PublicStreamN(obs)
        ps.advance(1499)
        pe = ps.to_engine_n(100)
        laws = {kind: ServiceLaw(15, .4, 180) for kind in ("cleaning", "transport")}
        result = posterior(pe, ps, laws, 10001, W.ProvN(sp, 10001))
        self.assertIn(st.sid, result.tr_service)
        self.assertEqual(result.tr_service, pe.tr_service)
        self.assertEqual(DeclaredService().unfinished(10**9), 1.)

    def test_legacy_arm_does_not_infer_transport_prerequisites(self):
        from correction import LegacyPublicStream
        sp = W.n_unit_structure("CORRECTION_TEST", 0, 4)
        eng = W.initial_engine(sp, W.ProvN(sp, 0))
        st = next(s for s in sorted(eng.stays.values(), key=lambda s: s.sid) if s.transport and s.dest is None and not s.aval)
        obs = W.static_obs(eng, sp) + [(60, 60, "transport_start", st.sid, st.unit, {})]
        out = {}
        for cls in (LegacyPublicStream, W.PublicStreamN):
            ps = cls(obs)
            ps.advance(89)
            out[cls] = ps.to_engine_n(6).stays[st.sid]
        self.assertFalse(out[LegacyPublicStream].ready or out[LegacyPublicStream].tr_accepted)
        self.assertTrue(out[W.PublicStreamN].ready and out[W.PublicStreamN].tr_accepted)


if __name__ == "__main__":
    unittest.main()
