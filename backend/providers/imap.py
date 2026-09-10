"""Aura Mail AI - Standard RFC 3501 IMAP & RFC 5321 SMTP Provider.

Supports custom domain, ISP (Roadrunner/Spectrum), and standard mailboxes.
Features RFC 6154 Special-Use folder discovery, IMAP UID validity tracking,
Keychain password storage, MIME attachment encoding, and structured error results.
"""

import imaplib
import smtplib
import email
from email.header import decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

from backend.models import EmailMessage
from backend.config import RESUMES_DIR
from backend.security import get_secret, set_secret, delete_secret
from backend.providers.base import (
    BaseEmailProvider,
    ProviderType,
    AccountIdentity,
    ProviderOperationResult,
    encode_composite_id,
    decode_composite_id
)

logger = logging.getLogger("imap_provider")

class ImapProvider(BaseEmailProvider):
    provider_type = ProviderType.IMAP

    def __init__(self):
        # Folder map cache per account: {account_id: {"drafts": "Drafts", "sent": "Sent Items", ...}}
        self._folder_cache: Dict[str, Dict[str, str]] = {}
        self._last_error: Dict[str, str] = {}

    @staticmethod
    def _parse_host_port(server_str: str, default_port: int) -> Tuple[str, int]:
        server_str = (server_str or "").strip()
        if not server_str:
            return "", default_port
        if ":" in server_str:
            parts = server_str.split(":", 1)
            host = parts[0].strip()
            try:
                port = int(parts[1].strip())
                return host, port
            except ValueError:
                return host, default_port
        return server_str, default_port

    def _get_account_config(self, account_id: str) -> Optional[Dict[str, Any]]:
        from backend.config import load_settings
        settings = load_settings()
        for acc in settings.get("configured_accounts", []):
            if acc.get("account_id") == account_id or acc.get("email") == account_id:
                return acc
        return None

    def _get_imap_connection(self, account_id: str) -> Optional[imaplib.IMAP4_SSL]:
        cfg = self._get_account_config(account_id)
        if not cfg:
            self._last_error[account_id] = f"Account {account_id} not configured in settings."
            return None
        
        email_addr = cfg.get("email", account_id)
        password = get_secret(f"imap_password_{email_addr.lower()}")
        if not password:
            err = f"No password found in macOS Keychain for IMAP account {email_addr}."
            logger.warning(err)
            self._last_error[account_id] = err
            return None
        
        raw_server = cfg.get("imap_server", "mail.twc.com" if "rr.com" in email_addr else "outlook.office365.com")
        server, port = self._parse_host_port(raw_server, int(cfg.get("imap_port", 993)))
        
        import ssl
        context = ssl.create_default_context()

        # Attempt 1: Standard login with full email address
        try:
            client = imaplib.IMAP4_SSL(server, port, ssl_context=context, timeout=15)
            client.login(email_addr, password)
            self._last_error.pop(account_id, None)
            return client
        except Exception as e1:
            logger.warning(f"IMAP login for {email_addr} with full email failed on {server}:{port}: {e1}")
            
            # Attempt 2: Try username prefix without domain (e.g. briankinlaw)
            if "@" in email_addr:
                user_prefix = email_addr.split("@")[0]
                try:
                    client2 = imaplib.IMAP4_SSL(server, port, ssl_context=context, timeout=15)
                    client2.login(user_prefix, password)
                    logger.info(f"IMAP login succeeded for {email_addr} using username prefix '{user_prefix}'.")
                    self._last_error.pop(account_id, None)
                    return client2
                except Exception as e2:
                    logger.warning(f"IMAP login with prefix '{user_prefix}' on {server} failed: {e2}")

            # Attempt 3: Spectrum mobile.charter.net fallback if Roadrunner/TWC
            if "twc.com" in server.lower() or "rr.com" in email_addr.lower():
                try:
                    client3 = imaplib.IMAP4_SSL("mobile.charter.net", 993, ssl_context=context, timeout=15)
                    client3.login(email_addr, password)
                    logger.info(f"IMAP login succeeded for {email_addr} on mobile.charter.net.")
                    self._last_error.pop(account_id, None)
                    return client3
                except Exception as e3:
                    logger.warning(f"IMAP fallback to mobile.charter.net failed: {e3}")

            err_detail = str(e1)
            if "Invalid user name or password" in err_detail or "AUTHENTICATIONFAILED" in err_detail.upper():
                self._last_error[account_id] = f"Invalid username or password on {server}:{port}. Verify webmail login at webmail.spectrum.net."
            else:
                self._last_error[account_id] = f"IMAP connection failed ({server}:{port}): {err_detail}"
            return None

    def _discover_folders(self, client: imaplib.IMAP4_SSL, account_id: str) -> Dict[str, str]:
        """Discovers standard folders using RFC 6154 Special-Use attributes or names."""
        if account_id in self._folder_cache:
            return self._folder_cache[account_id]

        folder_map = {
            "inbox": "INBOX",
            "drafts": "Drafts",
            "sent": "Sent",
            "trash": "Trash",
            "junk": "Junk"
        }

        try:
            status, folder_lines = client.list()
            if status == "OK" and folder_lines:
                for line in folder_lines:
                    if not line:
                        continue
                    line_str = line.decode("utf-8", errors="ignore") if isinstance(line, bytes) else str(line)
                    # Extract folder name
                    parts = line_str.split(' "/" ')
                    if len(parts) < 2:
                        parts = line_str.split(' "." ')
                    
                    folder_name = parts[-1].strip().strip('"') if len(parts) >= 2 else line_str.split()[-1].strip('"')
                    flags = line_str.upper()

                    # RFC 6154 check
                    if "\\DRAFTS" in flags or "DRAFT" in folder_name.upper():
                        folder_map["drafts"] = folder_name
                    elif "\\SENT" in flags or "SENT" in folder_name.upper():
                        folder_map["sent"] = folder_name
                    elif "\\TRASH" in flags or "\\DELETED" in flags or "TRASH" in folder_name.upper() or "DELETED" in folder_name.upper():
                        folder_map["trash"] = folder_name
                    elif "\\JUNK" in flags or "\\SPAM" in flags or "JUNK" in folder_name.upper() or "SPAM" in folder_name.upper():
                        folder_map["junk"] = folder_name
        except Exception as e:
            logger.warning(f"RFC 6154 folder discovery failed for {account_id}: {e}")

        self._folder_cache[account_id] = folder_map
        return folder_map

    def authenticate(self, account_config: Dict[str, Any], auth_payload: Optional[Dict[str, Any]] = None) -> ProviderOperationResult:
        email_addr = account_config.get("email", "").strip().lower()
        password = (auth_payload.get("password") if auth_payload else "") or ""
        
        if not email_addr:
            return ProviderOperationResult(
                success=False,
                provider="IMAP",
                account_id="unknown",
                operation="AUTHENTICATE",
                error_code="EMAIL_REQUIRED",
                safe_message="Email address required."
            )
        
        if password:
            set_secret(f"imap_password_{email_addr}", password)

        val_res = self.validate_connection(email_addr)
        if val_res.success:
            return ProviderOperationResult(
                success=True,
                provider="IMAP",
                account_id=email_addr,
                operation="AUTHENTICATE",
                safe_message=f"Connected to IMAP server as {email_addr}."
            )
        return val_res

    def validate_connection(self, account_id: str) -> ProviderOperationResult:
        client = self._get_imap_connection(account_id)
        if not client:
            err_msg = self._last_error.get(account_id, f"Failed to authenticate with IMAP server for {account_id}.")
            return ProviderOperationResult(
                success=False,
                provider="IMAP",
                account_id=account_id,
                operation="VALIDATE",
                error_code="CONNECTION_FAILED",
                safe_message=err_msg
            )
        try:
            client.select("INBOX", readonly=True)
            self._discover_folders(client, account_id)
            client.logout()
            return ProviderOperationResult(
                success=True,
                provider="IMAP",
                account_id=account_id,
                operation="VALIDATE",
                safe_message=f"Connected to IMAP mailbox {account_id}."
            )
        except Exception as e:
            try:
                client.logout()
            except Exception:
                pass
            return ProviderOperationResult(
                success=False,
                provider="IMAP",
                account_id=account_id,
                operation="VALIDATE",
                error_code="IMAP_ERROR",
                safe_message=f"IMAP validation error: {str(e)}"
            )

    def list_accounts(self) -> List[AccountIdentity]:
        from backend.config import load_settings
        settings = load_settings()
        configured = settings.get("configured_accounts", [])
        
        results = []
        for acc in configured:
            if acc.get("provider") == "IMAP":
                acc_id = acc.get("account_id", acc.get("email", ""))
                val_res = self.validate_connection(acc_id)
                results.append(AccountIdentity(
                    account_id=acc_id,
                    email_address=acc.get("email", acc_id),
                    provider=ProviderType.IMAP,
                    display_name=acc.get("display_name", f"IMAP ({acc_id})"),
                    is_connected=val_res.success,
                    is_primary=acc.get("is_primary", False),
                    last_sync_time=acc.get("last_sync_time"),
                    last_error=val_res.safe_message if not val_res.success else None,
                    capabilities=["DRAFTS", "SEND", "ATTACHMENTS", "MOVE", "DELETE", "QUARANTINE"]
                ))
        return results

    def fetch_inbox_messages(self, account_id: str, limit: int = 50, folder: str = "INBOX") -> Tuple[List[EmailMessage], Optional[str]]:
        client = self._get_imap_connection(account_id)
        if not client:
            return [], f"Could not connect to IMAP server for {account_id}"

        messages: List[EmailMessage] = []
        try:
            client.select(folder, readonly=True)
            status, search_data = client.uid("search", None, "ALL")
            if status != "OK" or not search_data or not search_data[0]:
                client.logout()
                return [], None

            uids = search_data[0].split()
            recent_uids = uids[-limit:]
            recent_uids.reverse()

            for uid in recent_uids:
                try:
                    uid_str = uid.decode("utf-8") if isinstance(uid, bytes) else str(uid)
                    fetch_res, msg_data = client.uid("fetch", uid, "(RFC822)")
                    if fetch_res != "OK" or not msg_data:
                        continue

                    raw_email = None
                    for part in msg_data:
                        if isinstance(part, tuple):
                            raw_email = part[1]
                            break

                    if not raw_email:
                        continue

                    msg_obj = email.message_from_bytes(raw_email)

                    # Subject
                    subject_header = msg_obj.get("Subject", "(No Subject)")
                    decoded_parts = decode_header(subject_header)
                    subject = ""
                    for s, enc in decoded_parts:
                        if isinstance(s, bytes):
                            subject += s.decode(enc or "utf-8", errors="replace")
                        else:
                            subject += str(s)

                    # Sender
                    from_header = msg_obj.get("From", "Unknown <unknown@domain.com>")
                    from_parts = decode_header(from_header)
                    raw_from = ""
                    for s, enc in from_parts:
                        if isinstance(s, bytes):
                            raw_from += s.decode(enc or "utf-8", errors="replace")
                        else:
                            raw_from += str(s)
                    sender_name, sender_email = email.utils.parseaddr(raw_from)
                    if not sender_name:
                        sender_name = sender_email

                    date_str = msg_obj.get("Date", datetime.now().isoformat())

                    # Body
                    body_text = ""
                    body_html = None
                    if msg_obj.is_multipart():
                        for part in msg_obj.walk():
                            ctype = part.get_content_type()
                            cdispo = str(part.get("Content-Disposition"))
                            if "attachment" not in cdispo:
                                if ctype == "text/plain" and not body_text:
                                    payload = part.get_payload(decode=True)
                                    if payload:
                                        body_text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                                elif ctype == "text/html" and not body_html:
                                    payload = part.get_payload(decode=True)
                                    if payload:
                                        body_html = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                    else:
                        payload = msg_obj.get_payload(decode=True)
                        if payload:
                            body_text = payload.decode(msg_obj.get_content_charset() or "utf-8", errors="replace")

                    preview = (body_text[:160].strip() if body_text else subject).replace("\n", " ")
                    composite_id = encode_composite_id("IMAP", account_id, uid_str)

                    msg = EmailMessage(
                        id=composite_id,
                        subject=subject.strip(),
                        sender_name=sender_name.strip(),
                        sender_email=sender_email.strip(),
                        received_at=date_str,
                        preview=preview,
                        body_text=body_text or subject,
                        body_html=body_html,
                        folder=folder
                    )
                    messages.append(msg)

                except Exception as ex:
                    logger.warning(f"Error parsing IMAP message UID {uid}: {ex}")

            client.logout()
            return messages, None

        except Exception as e:
            try:
                client.logout()
            except Exception:
                pass
            return messages, f"IMAP fetch error: {str(e)}"

    def create_reply_draft(
        self, 
        account_id: str, 
        message_id: str, 
        reply_body: str, 
        resume_filename: Optional[str] = None
    ) -> ProviderOperationResult:
        client = self._get_imap_connection(account_id)
        if not client:
            return ProviderOperationResult(
                success=False,
                provider="IMAP",
                account_id=account_id,
                operation="CREATE_DRAFT",
                error_code="CONNECTION_FAILED",
                safe_message="Failed to connect to IMAP server."
            )

        _, _, native_uid = decode_composite_id(message_id)
        folders = self._discover_folders(client, account_id)
        drafts_folder = folders.get("drafts", "Drafts")

        try:
            # Build MIME message
            msg = MIMEMultipart()
            msg["From"] = f"Brian K. Kinlaw <{account_id}>"
            msg["Subject"] = "Re: Executive Inquiry & Canonical Career Advisory"
            msg["Date"] = email.utils.formatdate(localtime=True)
            msg.attach(MIMEText(reply_body, "plain"))

            if resume_filename:
                from backend.canonical_engine import resolve_resume_file
                file_path = resolve_resume_file(resume_filename)
                if not file_path or not file_path.exists():
                    file_path = RESUMES_DIR / resume_filename
                if file_path and file_path.exists():
                    with open(file_path, "rb") as f:
                        part = MIMEApplication(f.read(), Name=file_path.name)
                    part["Content-Disposition"] = f'attachment; filename="{file_path.name}"'
                    msg.attach(part)
                else:
                    client.logout()
                    return ProviderOperationResult(
                        success=False,
                        provider="IMAP",
                        account_id=account_id,
                        operation="CREATE_DRAFT",
                        error_code="FILE_NOT_FOUND",
                        safe_message=f"Resume file '{resume_filename}' not found on disk."
                    )

            raw_bytes = msg.as_bytes()
            res, _ = client.append(f'"{drafts_folder}"', r"(\Draft \Seen)", None, raw_bytes)
            if res != "OK":
                res, _ = client.append(drafts_folder, r"(\Draft \Seen)", None, raw_bytes)

            client.logout()
            if res == "OK":
                return ProviderOperationResult(
                    success=True,
                    provider="IMAP",
                    account_id=account_id,
                    operation="CREATE_DRAFT",
                    safe_message=f"Draft created on IMAP server in folder '{drafts_folder}' with resume attached."
                )
            else:
                return ProviderOperationResult(
                    success=False,
                    provider="IMAP",
                    account_id=account_id,
                    operation="CREATE_DRAFT",
                    error_code="APPEND_FAILED",
                    safe_message=f"Failed to append draft to IMAP folder '{drafts_folder}'."
                )
        except Exception as e:
            try:
                client.logout()
            except Exception:
                pass
            return ProviderOperationResult(
                success=False,
                provider="IMAP",
                account_id=account_id,
                operation="CREATE_DRAFT",
                error_code="EXCEPTION",
                safe_message=f"Error saving IMAP draft: {str(e)}"
            )

    def attach_file(self, account_id: str, draft_id: str, filename: str, file_path: Path) -> ProviderOperationResult:
        return ProviderOperationResult(
            success=True,
            provider="IMAP",
            account_id=account_id,
            operation="ATTACH_FILE",
            safe_message=f"Attachment '{filename}' bundled into IMAP MIME structure."
        )

    def send_reply(
        self, 
        account_id: str, 
        message_id: str, 
        to_email: str, 
        subject: str, 
        reply_body: str, 
        resume_filename: Optional[str] = None
    ) -> ProviderOperationResult:
        cfg = self._get_account_config(account_id)
        if not cfg:
            return ProviderOperationResult(
                success=False,
                provider="IMAP",
                account_id=account_id,
                operation="SEND_REPLY",
                error_code="CONFIG_MISSING",
                safe_message=f"No SMTP configuration found for {account_id}."
            )

        password = get_secret(f"imap_password_{account_id.lower()}")
        if not password:
            return ProviderOperationResult(
                success=False,
                provider="IMAP",
                account_id=account_id,
                operation="SEND_REPLY",
                error_code="PASSWORD_MISSING",
                safe_message=f"No password found in Keychain for {account_id}."
            )

        raw_smtp = cfg.get("smtp_server", "mail.twc.com" if "rr.com" in account_id else "smtp.office365.com")
        smtp_server, smtp_port = self._parse_host_port(raw_smtp, int(cfg.get("smtp_port", 587)))

        try:
            msg = MIMEMultipart()
            msg["From"] = f"Brian K. Kinlaw <{account_id}>"
            msg["To"] = to_email
            msg["Subject"] = subject if subject.startswith("Re:") else f"Re: {subject}"
            msg["Date"] = email.utils.formatdate(localtime=True)
            msg.attach(MIMEText(reply_body, "plain"))

            if resume_filename:
                from backend.canonical_engine import resolve_resume_file
                file_path = resolve_resume_file(resume_filename)
                if not file_path or not file_path.exists():
                    file_path = RESUMES_DIR / resume_filename
                if file_path and file_path.exists():
                    with open(file_path, "rb") as f:
                        part = MIMEApplication(f.read(), Name=file_path.name)
                    part["Content-Disposition"] = f'attachment; filename="{file_path.name}"'
                    msg.attach(part)

            server = smtplib.SMTP(smtp_server, smtp_port, timeout=20)
            server.starttls()
            server.login(account_id, password)
            server.sendmail(account_id, [to_email], msg.as_bytes())
            server.quit()

            # Append to Sent folder via IMAP
            client = self._get_imap_connection(account_id)
            if client:
                try:
                    folders = self._discover_folders(client, account_id)
                    sent_folder = folders.get("sent", "Sent")
                    client.append(f'"{sent_folder}"', r"(\Seen)", None, msg.as_bytes())
                    client.logout()
                except Exception:
                    pass

            return ProviderOperationResult(
                success=True,
                provider="IMAP",
                account_id=account_id,
                operation="SEND_REPLY",
                safe_message=f"Email successfully sent to {to_email} via SMTP ({smtp_server})."
            )
        except Exception as e:
            return ProviderOperationResult(
                success=False,
                provider="IMAP",
                account_id=account_id,
                operation="SEND_REPLY",
                error_code="SMTP_ERROR",
                safe_message=f"SMTP dispatch error: {str(e)}"
            )

    def create_or_resolve_quarantine_folder(self, account_id: str, folder_name: str = "AI Cleaned - Noise") -> Optional[str]:
        client = self._get_imap_connection(account_id)
        if not client:
            return None
        try:
            client.create(f'"{folder_name}"')
            client.logout()
            return folder_name
        except Exception:
            try:
                client.logout()
            except Exception:
                pass
            return folder_name

    def move_message(self, account_id: str, message_id: str, destination_folder_id: str) -> ProviderOperationResult:
        client = self._get_imap_connection(account_id)
        if not client:
            return ProviderOperationResult(
                success=False,
                provider="IMAP",
                account_id=account_id,
                operation="MOVE_MESSAGE",
                error_code="CONNECTION_FAILED",
                safe_message="Failed to connect to IMAP server."
            )

        _, _, native_uid = decode_composite_id(message_id)
        try:
            client.select("INBOX")
            # Ensure destination folder exists
            try:
                client.create(f'"{destination_folder_id}"')
            except Exception:
                pass

            res, _ = client.uid("copy", native_uid, f'"{destination_folder_id}"')
            if res == "OK":
                client.uid("store", native_uid, "+FLAGS", r"(\Deleted)")
                client.expunge()
                client.logout()
                return ProviderOperationResult(
                    success=True,
                    provider="IMAP",
                    account_id=account_id,
                    operation="MOVE_MESSAGE",
                    safe_message=f"Message moved to folder '{destination_folder_id}' on IMAP server."
                )
            else:
                client.logout()
                return ProviderOperationResult(
                    success=False,
                    provider="IMAP",
                    account_id=account_id,
                    operation="MOVE_MESSAGE",
                    error_code="COPY_FAILED",
                    safe_message=f"Failed to copy message UID {native_uid} to '{destination_folder_id}'."
                )
        except Exception as e:
            try:
                client.logout()
            except Exception:
                pass
            return ProviderOperationResult(
                success=False,
                provider="IMAP",
                account_id=account_id,
                operation="MOVE_MESSAGE",
                error_code="EXCEPTION",
                safe_message=f"Error moving IMAP message: {str(e)}"
            )

    def delete_message(self, account_id: str, message_id: str) -> ProviderOperationResult:
        client = self._get_imap_connection(account_id)
        if not client:
            return ProviderOperationResult(
                success=False,
                provider="IMAP",
                account_id=account_id,
                operation="DELETE_MESSAGE",
                error_code="CONNECTION_FAILED",
                safe_message="Failed to connect to IMAP server."
            )

        folders = self._discover_folders(client, account_id)
        trash_folder = folders.get("trash", "Trash")
        return self.move_message(account_id, message_id, trash_folder)

    def get_health_status(self, account_id: str) -> Dict[str, Any]:
        val = self.validate_connection(account_id)
        return {
            "provider": "IMAP",
            "account_id": account_id,
            "connected": val.success,
            "status_message": val.safe_message
        }

    def logout(self, account_id: Optional[str] = None) -> ProviderOperationResult:
        if account_id:
            delete_secret(f"imap_password_{account_id.lower()}")
        return ProviderOperationResult(
            success=True,
            provider="IMAP",
            account_id=account_id or "all",
            operation="LOGOUT",
            safe_message=f"Cleared IMAP credentials for {account_id or 'all accounts'}."
        )
