"""Transactional emails (invitation, password reset): SMTP in staging/production, console in
development.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol

from .config import Settings, SmtpSettings

LOG = logging.getLogger("hospitalos.platform.email")


@dataclass(frozen=True)
class Message:
    to: str
    subject: str
    text: str


class Mailer(Protocol):
    def send(self, message: Message) -> None: ...


@dataclass
class ConsoleMailer:
    """Development only: messages are logged (links included) and kept in memory for tests."""

    sent: list[Message] = field(default_factory=list)

    def send(self, message: Message) -> None:
        self.sent.append(message)
        LOG.warning(
            "EMAIL (console backend) to=%s subject=%s\n%s",
            message.to,
            message.subject,
            message.text,
        )


class SmtpMailer:
    def __init__(self, smtp: SmtpSettings, sender: str) -> None:
        self.smtp, self.sender = smtp, sender

    def send(self, message: Message) -> None:
        mail = EmailMessage()
        mail["From"], mail["To"], mail["Subject"] = self.sender, message.to, message.subject
        mail.set_content(message.text)
        with smtplib.SMTP(self.smtp.host, self.smtp.port, timeout=20) as client:
            if self.smtp.starttls:
                client.starttls(context=ssl.create_default_context())
            client.login(self.smtp.username, self.smtp.password)
            client.send_message(mail)


def mailer_for(settings: Settings) -> Mailer:
    if settings.email_backend == "smtp":
        assert settings.smtp is not None
        return SmtpMailer(settings.smtp, settings.email_from)
    return ConsoleMailer()


def invitation(to: str, link: str, inviter: str, days: int) -> Message:
    return Message(
        to=to,
        subject="Votre accès au pilote HospitalOS",
        text=(
            "Bonjour,\n\n"
            f"{inviter} vous invite à rejoindre le pilote HospitalOS (aide à la décision lits et "
            "sorties, "
            "mode observation).\n\n"
            f"Pour créer votre mot de passe, ouvrez ce lien (valable {days} jours, une seule "
            f"fois) :\n{link}\n\n"
            "Si vous n'attendiez pas cette invitation, ignorez ce message.\n\nHospitalOS"
        ),
    )


def password_reset(to: str, link: str, minutes: int) -> Message:
    return Message(
        to=to,
        subject="Réinitialisation de votre mot de passe HospitalOS",
        text=(
            "Bonjour,\n\n"
            "Une réinitialisation du mot de passe de votre compte HospitalOS a été demandée.\n\n"
            f"Pour choisir un nouveau mot de passe, ouvrez ce lien (valable {minutes} minutes, "
            "une seule fois) :\n"
            f"{link}\n\n"
            "Si vous n'êtes pas à l'origine de cette demande, ignorez ce message : votre mot de "
            "passe reste "
            "inchangé.\n\nHospitalOS"
        ),
    )
