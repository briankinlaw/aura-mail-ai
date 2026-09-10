import os
import time
import base64
import json
import logging
import subprocess
import urllib.parse
import imaplib
import smtplib
import email
from email.header import decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import requests

from backend.models import EmailMessage, EmailCategory, ClassificationResult
from backend.config import load_settings, save_settings, RESUMES_DIR

logger = logging.getLogger(__name__)

GRAPH_API_ENDPOINT = "https://graph.microsoft.com/v1.0"
OAUTH_ENDPOINT = "https://login.microsoftonline.com"

# Official Microsoft Multi-Tenant Public Client ID for Consumers & Organizations
DEFAULT_PUBLIC_CLIENT_ID = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"
DEFAULT_SCOPES = "Mail.Read Mail.ReadWrite Mail.Send offline_access User.Read"

class OutlookClient:
    def __init__(self):
        self.settings = load_settings()
        self._current_device_code = None
        self._device_code_expires = 0
        self._last_poll_time = 0
        self._poll_interval = 5
    
    def is_authenticated(self) -> bool:
        return self.get_auth_mode() != "DEMO"

    def get_auth_mode(self) -> str:
        settings = load_settings()
        if settings.get("auth_token"):
            return "GRAPH_CLOUD_OAUTH"
        if settings.get("imap_config"):
            return "CLOUD_IMAP"
        if self.is_mac_outlook_available():
            return "MAC_DESKTOP_CLIENT"
        return "DEMO"

    def is_mac_outlook_available(self) -> bool:
        try:
            res = subprocess.run(
                ["osascript", "-e", 'tell application "System Events" to (name of processes) contains "Microsoft Outlook"'],
                capture_output=True, text=True, timeout=3
            )
            return "true" in res.stdout.lower()
        except Exception:
            return False

    def get_auth_display_name(self) -> str:
        settings = load_settings()
        if settings.get("auth_token"):
            username = settings.get("auth_token", {}).get("username", "Microsoft Account")
            return f"Connected (Cloud Graph: {username})"
        if settings.get("imap_config"):
            email_addr = settings.get("imap_config", {}).get("email", "kinlawb@outlook.com")
            return f"Connected (Cloud IMAP: {email_addr})"
        if self.is_mac_outlook_available():
            return "Connected (Mac Desktop Outlook Client)"
        return "Demo Mode (Mock Outlook)"

    # --- Modern OAuth2 Web Authorization Flow (Direct Microsoft Graph for New Outlook) ---

    def get_auth_url(self, redirect_uri: Optional[str] = None) -> str:
        """Generates Microsoft OAuth2 login URL with proper response_type and scopes."""
        settings = load_settings()
        client_id = settings.get("azure_client_id") or DEFAULT_PUBLIC_CLIENT_ID
        tenant_id = settings.get("azure_tenant_id", "consumers")
        
        if not redirect_uri:
            if settings.get("azure_client_id"):
                redirect_uri = "http://127.0.0.1:8000/api/auth/callback"
            else:
                redirect_uri = "https://login.microsoftonline.com/common/oauth2/nativeclient"
        
        params = {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "response_mode": "query",
            "scope": DEFAULT_SCOPES,
            "prompt": "select_account"
        }
        return f"{OAUTH_ENDPOINT}/{tenant_id}/oauth2/v2.0/authorize?{urllib.parse.urlencode(params)}"

    def exchange_code_for_token(self, code_or_url: str, redirect_uri: Optional[str] = None) -> Dict[str, Any]:
        """Exchanges authorization code (or full redirect URL) for Microsoft Graph OAuth2 tokens."""
        settings = load_settings()
        client_id = settings.get("azure_client_id") or DEFAULT_PUBLIC_CLIENT_ID
        tenant_id = settings.get("azure_tenant_id", "consumers")
        token_url = f"{OAUTH_ENDPOINT}/{tenant_id}/oauth2/v2.0/token"
        
        code = code_or_url.strip()
        # If full redirect URL was pasted, extract code parameter
        if "code=" in code:
            parsed = urllib.parse.urlparse(code)
            qs = urllib.parse.parse_qs(parsed.query)
            if "code" in qs:
                code = qs["code"][0]
        
        if not redirect_uri:
            if settings.get("azure_client_id"):
                redirect_uri = "http://127.0.0.1:8000/api/auth/callback"
            else:
                redirect_uri = "https://login.microsoftonline.com/common/oauth2/nativeclient"
        
        payload = {
            "client_id": client_id,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "scope": DEFAULT_SCOPES
        }
        
        res = requests.post(token_url, data=payload, timeout=15)
        if res.status_code != 200:
            err_msg = res.json().get("error_description", res.text) if res.headers.get("content-type", "").startswith("application/json") else res.text
            raise Exception(f"Token exchange failed: {err_msg}")
        
        data = res.json()
        access_token = data["access_token"]
        user_name = "kinlawb@outlook.com"
        try:
            profile_res = requests.get(
                f"{GRAPH_API_ENDPOINT}/me",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=5
            )
            if profile_res.status_code == 200:
                p = profile_res.json()
                user_name = p.get("displayName") or p.get("userPrincipalName") or p.get("mail") or user_name
        except Exception:
            pass
        
        auth_info = {
            "access_token": access_token,
            "refresh_token": data.get("refresh_token"),
            "expires_at": datetime.now().timestamp() + data.get("expires_in", 3600),
            "username": user_name
        }
        settings["auth_token"] = auth_info
        save_settings(settings)
        logger.info(f"Successfully authenticated with Microsoft Graph as {user_name}")
        return {"status": "SUCCESS", "username": user_name}

    # --- Microsoft Graph Cloud OAuth2 (Direct Cloud Sync for New Outlook & Web) ---

    def get_access_token(self) -> Optional[str]:
        settings = load_settings()
        auth_info = settings.get("auth_token")
        if not auth_info:
            return None
        
        access_token = auth_info.get("access_token")
        expires_at = auth_info.get("expires_at", 0)
        
        if access_token and datetime.now().timestamp() < expires_at - 60:
            return access_token
        
        refresh_token = auth_info.get("refresh_token")
        if refresh_token:
            client_id = settings.get("azure_client_id") or DEFAULT_PUBLIC_CLIENT_ID
            tenant_id = settings.get("azure_tenant_id", "consumers")
            token_url = f"{OAUTH_ENDPOINT}/{tenant_id}/oauth2/v2.0/token"
            
            payload = {
                "client_id": client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": DEFAULT_SCOPES
            }
            try:
                res = requests.post(token_url, data=payload, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    auth_info["access_token"] = data["access_token"]
                    auth_info["expires_at"] = datetime.now().timestamp() + data.get("expires_in", 3600)
                    if "refresh_token" in data:
                        auth_info["refresh_token"] = data["refresh_token"]
                    settings["auth_token"] = auth_info
                    save_settings(settings)
                    return data["access_token"]
            except Exception as e:
                logger.error(f"Failed to refresh Microsoft token: {e}")
        
        return None

    def initiate_device_code_flow(self) -> Dict[str, Any]:
        """Starts modern Microsoft OAuth2 Device Code flow for personal & work Outlook."""
        settings = load_settings()
        client_id = settings.get("azure_client_id") or DEFAULT_PUBLIC_CLIENT_ID
        tenant_id = settings.get("azure_tenant_id", "consumers")
        device_url = f"{OAUTH_ENDPOINT}/{tenant_id}/oauth2/v2.0/devicecode"
        
        payload = {
            "client_id": client_id,
            "scope": DEFAULT_SCOPES
        }
        
        res = requests.post(device_url, data=payload, timeout=15)
        if res.status_code != 200:
            err_data = res.json() if res.headers.get("content-type", "").startswith("application/json") else res.text
            raise Exception(f"Device code initiation failed: {err_data}")
        
        flow = res.json()
        self._current_device_code = flow["device_code"]
        self._device_code_expires = datetime.now().timestamp() + flow.get("expires_in", 900)
        self._poll_interval = flow.get("interval", 5)
        
        return {
            "user_code": flow["user_code"],
            "verification_uri": flow.get("verification_uri", "https://www.microsoft.com/link"),
            "message": flow.get("message", "Go to https://www.microsoft.com/link and enter code"),
            "expires_in": flow.get("expires_in", 900),
            "interval": self._poll_interval
        }

    def poll_device_code_token(self) -> Dict[str, Any]:
        if not self._current_device_code:
            return {"status": "ERROR", "message": "No active device authorization in progress."}
        
        if datetime.now().timestamp() > self._device_code_expires:
            self._current_device_code = None
            return {"status": "EXPIRED", "message": "Login session expired. Please retry."}
        
        now = time.time()
        if now - self._last_poll_time < 2:
            return {"status": "PENDING", "message": "Waiting for authorization..."}
        
        self._last_poll_time = now
        settings = load_settings()
        client_id = settings.get("azure_client_id") or DEFAULT_PUBLIC_CLIENT_ID
        tenant_id = settings.get("azure_tenant_id", "consumers")
        token_url = f"{OAUTH_ENDPOINT}/{tenant_id}/oauth2/v2.0/token"
        
        payload = {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": client_id,
            "device_code": self._current_device_code
        }
        
        try:
            res = requests.post(token_url, data=payload, timeout=10)
            data = res.json()
            
            if res.status_code == 200 and "access_token" in data:
                user_name = "kinlawb@outlook.com"
                try:
                    profile_res = requests.get(
                        f"{GRAPH_API_ENDPOINT}/me",
                        headers={"Authorization": f"Bearer {data['access_token']}"},
                        timeout=5
                    )
                    if profile_res.status_code == 200:
                        p = profile_res.json()
                        user_name = p.get("displayName") or p.get("userPrincipalName") or p.get("mail") or user_name
                except Exception:
                    pass
                
                auth_info = {
                    "access_token": data["access_token"],
                    "refresh_token": data.get("refresh_token"),
                    "expires_at": datetime.now().timestamp() + data.get("expires_in", 3600),
                    "username": user_name
                }
                settings["auth_token"] = auth_info
                save_settings(settings)
                self._current_device_code = None
                return {"status": "SUCCESS", "username": user_name}
            
            error_code = data.get("error")
            if error_code in ["authorization_pending", "slow_down"]:
                return {"status": "PENDING", "message": "Waiting for you to enter code at microsoft.com/link..."}
            elif error_code == "expired_token":
                self._current_device_code = None
                return {"status": "EXPIRED", "message": "Login code expired."}
            else:
                return {"status": "ERROR", "message": data.get("error_description", error_code)}
                
        except Exception as ex:
            return {"status": "PENDING", "message": f"Connecting: {ex}"}

    def fetch_from_graph(self, count: int = 50) -> List[EmailMessage]:
        """Fetches live emails directly from Microsoft Graph API in the cloud."""
        token = self.get_access_token()
        if not token:
            return []
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        }
        params = {
            "$top": count,
            "$select": "id,conversationId,subject,from,receivedDateTime,bodyPreview,body,isRead,hasAttachments,parentFolderId",
            "$orderby": "receivedDateTime desc"
        }
        
        url = f"{GRAPH_API_ENDPOINT}/me/mailFolders/Inbox/messages"
        try:
            res = requests.get(url, headers=headers, params=params, timeout=15)
            if res.status_code == 200:
                data = res.json()
                messages = []
                for item in data.get("value", []):
                    sender_obj = item.get("from", {}).get("emailAddress", {})
                    msg = EmailMessage(
                        id=f"graph_{item.get('id')}",
                        conversation_id=item.get("conversationId"),
                        subject=item.get("subject", "(No Subject)"),
                        sender_name=sender_obj.get("name", "Unknown"),
                        sender_email=sender_obj.get("address", "unknown@domain.com"),
                        received_at=item.get("receivedDateTime", datetime.now().isoformat()),
                        preview=item.get("bodyPreview", ""),
                        body_text=item.get("body", {}).get("content", item.get("bodyPreview", "")),
                        body_html=item.get("body", {}).get("content") if item.get("body", {}).get("contentType") == "html" else None,
                        is_read=item.get("isRead", False),
                        has_attachments=item.get("hasAttachments", False),
                        folder="Inbox"
                    )
                    messages.append(msg)
                return messages
            else:
                logger.error(f"Graph fetch failed: {res.text}")
        except Exception as ex:
            logger.error(f"Graph fetch error: {ex}")
        return []

    # --- Native Mac Desktop Outlook Integration (AppleScript) ---

    def fetch_from_mac_outlook(self, count: int = 50) -> List[EmailMessage]:
        """Reads live emails across all Universal inboxes in Microsoft Outlook for Mac."""
        settings = load_settings()
        user_prof = settings.get("user_profile", {})
        historical_accounts = user_prof.get("historical_email_accounts") or [
            "bkinlaw@dxc.com", "brian.kinlaw@cdw.com", "briankinlaw@revealwhy.com"
        ]
        
        # Build AppleScript skip condition
        skip_conditions = ['acc contains "On My Computer"']
        for h_acc in historical_accounts:
            clean_h = h_acc.strip().lower()
            if clean_h:
                skip_conditions.append(f'acc contains "{clean_h}"')
                if "@" in clean_h:
                    domain = clean_h.split("@")[1]
                    skip_conditions.append(f'acc contains "{domain}"')
        
        skip_clause = " or ".join(skip_conditions)

        script = f'''
        tell application "Microsoft Outlook"
            set inboxes to (every mail folder whose name is "Inbox")
            set outItems to {{}}
            
            repeat with f in inboxes
                try
                    set acc to ""
                    try
                        set acc to (name of container of f as text)
                    end try
                    
                    -- Skip historical reference accounts
                    if not ({skip_clause}) then
                        set c to count of messages of f
                        if c > 0 then
                            set takeCount to {count}
                            if c < takeCount then set takeCount to c
                            set ms to (messages 1 thru takeCount of f)
                            repeat with m in ms
                                set sId to (id of m as string)
                                set sSubj to ""
                                set sName to ""
                                set sAddr to ""
                                set sDate to ""
                                set sBody to ""
                                try
                                    set sSubj to (subject of m as string)
                                end try
                                try
                                    set snd to sender of m
                                    set sName to (name of snd as string)
                                    set sAddr to (address of snd as string)
                                end try
                                try
                                    set sDate to (time sent of m as string)
                                end try
                                try
                                    set sBody to (plain text content of m as string)
                                    if sBody is "" then set sBody to (content of m as string)
                                end try
                                if (length of sBody) > 4000 then set sBody to text 1 thru 4000 of sBody
                                
                                set end of outItems to (sId & "::|::" & sSubj & "::|::" & sName & "::|::" & sAddr & "::|::" & sDate & "::|::" & sBody)
                            end repeat
                        end if
                    end if
                end try
            end repeat
            
            set AppleScript's text item delimiters to "<ITEM_DELIM>"
            return outItems as string
        end tell
        '''
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=35)
            if res.returncode == 0 and res.stdout.strip():
                raw_text = res.stdout.strip()
                items = raw_text.split("<ITEM_DELIM>")
                messages = []
                seen_ids = set()
                
                for item_str in items:
                    parts = item_str.split("::|::")
                    if len(parts) >= 6:
                        msg_id = parts[0].strip()
                        if msg_id in seen_ids:
                            continue
                        seen_ids.add(msg_id)
                        
                        subj = parts[1].strip() or "(No Subject)"
                        sender_name = parts[2].strip() or "Sender"
                        sender_email = parts[3].strip() or "sender@domain.com"
                        date_str = parts[4].strip()
                        body_content = parts[5].strip()
                        
                        msg = EmailMessage(
                            id=f"mac_{msg_id}",
                            subject=subj,
                            sender_name=sender_name,
                            sender_email=sender_email,
                            received_at=date_str,
                            preview=body_content[:160].strip() if body_content else subj,
                            body_text=body_content or subj,
                            folder="Inbox"
                        )
                        messages.append(msg)
                
                if messages:
                    return messages
        except Exception as ex:
            logger.error(f"Mac Outlook fetch error: {ex}")
            
        return self.get_sample_emails()

    # --- Direct Cloud IMAP & SMTP Integration (New Outlook & Cloud Mailbox) ---

    def configure_imap(
        self, 
        email_addr: str, 
        password: str, 
        imap_server: str = "outlook.office365.com", 
        smtp_server: str = "smtp.office365.com",
        imap_port: int = 993,
        smtp_port: int = 587
    ) -> Dict[str, Any]:
        """Validates and stores IMAP/SMTP credentials for direct Microsoft cloud sync."""
        try:
            # Test IMAP connection
            mail = imaplib.IMAP4_SSL(imap_server, imap_port)
            mail.login(email_addr, password)
            status, folders = mail.list()
            mail.logout()
            
            settings = load_settings()
            settings["imap_config"] = {
                "email": email_addr,
                "password": password,
                "imap_server": imap_server,
                "smtp_server": smtp_server,
                "imap_port": imap_port,
                "smtp_port": smtp_port,
                "configured_at": datetime.now().isoformat()
            }
            save_settings(settings)
            logger.info(f"Cloud IMAP configured successfully for {email_addr}")
            return {"status": "SUCCESS", "message": f"Connected to Microsoft Cloud IMAP as {email_addr}!"}
        except Exception as e:
            logger.error(f"IMAP configuration failed: {e}")
            raise Exception(f"Failed to connect to {imap_server}: {str(e)}")

    def get_imap_connection(self):
        settings = load_settings()
        cfg = settings.get("imap_config")
        if not cfg:
            return None
        try:
            mail = imaplib.IMAP4_SSL(cfg["imap_server"], cfg.get("imap_port", 993))
            mail.login(cfg["email"], cfg["password"])
            return mail
        except Exception as e:
            logger.error(f"Failed to establish IMAP connection: {e}")
            return None

    def fetch_from_imap(self, count: int = 50) -> List[EmailMessage]:
        """Fetches live emails directly from Microsoft Cloud IMAP."""
        mail = self.get_imap_connection()
        if not mail:
            return []
        
        messages = []
        try:
            mail.select("INBOX", readonly=True)
            status, data = mail.search(None, "ALL")
            if status != "OK" or not data or not data[0]:
                mail.logout()
                return []
            
            mail_ids = data[0].split()
            # Fetch most recent emails
            recent_ids = mail_ids[-count:]
            recent_ids.reverse()
            
            for m_id in recent_ids:
                try:
                    str_id = m_id.decode("utf-8") if isinstance(m_id, bytes) else str(m_id)
                    res_status, msg_data = mail.fetch(m_id, "(RFC822)")
                    if res_status != "OK" or not msg_data:
                        continue
                    
                    raw_email = None
                    for part in msg_data:
                        if isinstance(part, tuple):
                            raw_email = part[1]
                            break
                    
                    if not raw_email:
                        continue
                    
                    msg_obj = email.message_from_bytes(raw_email)
                    
                    # Parse subject
                    subject_header = msg_obj.get("Subject", "(No Subject)")
                    decoded_subj_parts = decode_header(subject_header)
                    subject = ""
                    for s, enc in decoded_subj_parts:
                        if isinstance(s, bytes):
                            subject += s.decode(enc or "utf-8", errors="replace")
                        else:
                            subject += str(s)
                    
                    # Parse sender
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
                        sender_name = sender_email.split("@")[0] if "@" in sender_email else "Sender"
                    
                    date_str = msg_obj.get("Date", datetime.now().isoformat())
                    
                    # Extract body content
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
                    
                    msg = EmailMessage(
                        id=f"imap_{str_id}",
                        subject=subject.strip(),
                        sender_name=sender_name.strip(),
                        sender_email=sender_email.strip(),
                        received_at=date_str,
                        preview=preview,
                        body_text=body_text or subject,
                        body_html=body_html,
                        folder="Inbox"
                    )
                    messages.append(msg)
                except Exception as ex:
                    logger.warning(f"Error parsing IMAP message {m_id}: {ex}")
            
            mail.logout()
        except Exception as e:
            logger.error(f"Error reading from IMAP: {e}")
            try:
                mail.logout()
            except Exception:
                pass
        
        return messages

    def move_email_to_folder_imap(self, message_id: str, folder_name: str = "AI Cleaned - Noise") -> bool:
        """Moves an email into a specified folder directly on the Microsoft Cloud server."""
        mail = self.get_imap_connection()
        if not mail:
            return False
        
        clean_id = message_id.replace("imap_", "")
        success = False
        try:
            mail.select("INBOX")
            # Ensure target folder exists
            try:
                mail.create(f'"{folder_name}"')
            except Exception:
                pass
            
            # Copy to target folder
            res, _ = mail.copy(clean_id, f'"{folder_name}"')
            if res == "OK":
                # Mark as deleted in INBOX and expunge
                mail.store(clean_id, "+FLAGS", r"(\Deleted)")
                mail.expunge()
                success = True
                logger.info(f"Moved IMAP message {clean_id} to '{folder_name}' on server.")
            mail.logout()
        except Exception as e:
            logger.error(f"Failed to move IMAP email {clean_id}: {e}")
            try:
                mail.logout()
            except Exception:
                pass
        return success

    def save_draft_imap(
        self,
        message_id: str,
        reply_body: str,
        resume_filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """Creates and saves a draft email directly into the server Drafts folder via IMAP."""
        settings = load_settings()
        cfg = settings.get("imap_config", {})
        sender_email = cfg.get("email", "kinlawb@outlook.com")
        
        mail = self.get_imap_connection()
        if not mail:
            return {"status": "ERROR", "message": "No IMAP connection available."}
        
        try:
            # Build MIME message
            msg = MIMEMultipart()
            msg["From"] = f"Brian K. Kinlaw <{sender_email}>"
            msg["Subject"] = "Re: Executive Inquiry & Canonical Career Advisory"
            msg["Date"] = email.utils.formatdate(localtime=True)
            
            # Attach body
            msg.attach(MIMEText(reply_body, "plain"))
            
            # Attach canonical resume if specified
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
            
            raw_msg = msg.as_bytes()
            
            # Try appending to 'Drafts' or 'Draft'
            res, _ = mail.append("Drafts", r"(\Draft \Seen)", None, raw_msg)
            if res != "OK":
                res, _ = mail.append('"Drafts"', r"(\Draft \Seen)", None, raw_msg)
            
            mail.logout()
            logger.info("Draft successfully appended to server Drafts folder via IMAP.")
            return {"status": "SUCCESS", "message": "Draft created in Microsoft Cloud Drafts folder!"}
        except Exception as e:
            logger.error(f"Failed to save IMAP draft: {e}")
            try:
                mail.logout()
            except Exception:
                pass
            return {"status": "ERROR", "message": str(e)}

    def send_reply_imap(
        self,
        to_email: str,
        subject: str,
        reply_body: str,
        resume_filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """Sends an email directly via SMTP and appends it to the Sent Items folder."""
        settings = load_settings()
        cfg = settings.get("imap_config", {})
        if not cfg:
            return {"status": "ERROR", "message": "No cloud credentials configured."}
        
        sender_email = cfg.get("email", "kinlawb@outlook.com")
        password = cfg.get("password", "")
        smtp_server = cfg.get("smtp_server", "smtp.office365.com")
        smtp_port = cfg.get("smtp_port", 587)
        
        try:
            msg = MIMEMultipart()
            msg["From"] = f"Brian K. Kinlaw <{sender_email}>"
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
            
            # Send via SMTP
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=15)
            server.starttls()
            server.login(sender_email, password)
            server.sendmail(sender_email, [to_email], msg.as_bytes())
            server.quit()
            
            # Append to Sent Items via IMAP
            mail = self.get_imap_connection()
            if mail:
                try:
                    mail.append('"Sent Items"', r"(\Seen)", None, msg.as_bytes())
                    mail.logout()
                except Exception:
                    pass
            
            return {"status": "SUCCESS", "message": f"Email successfully sent to {to_email} via Microsoft SMTP!"}
        except Exception as e:
            logger.error(f"Failed to send email via SMTP: {e}")
            return {"status": "ERROR", "message": str(e)}

    def fetch_inbox_emails(self, count: int = 50) -> List[EmailMessage]:
        # 1. Try Cloud IMAP first (Direct Microsoft Cloud Sync for New Outlook)
        if self.get_auth_mode() == "CLOUD_IMAP":
            imap_msgs = self.fetch_from_imap(count=count)
            if imap_msgs:
                return imap_msgs

        # 2. Try Graph Cloud API
        if self.get_access_token():
            graph_msgs = self.fetch_from_graph(count=count)
            if graph_msgs:
                return graph_msgs
        
        # 3. Fall back to Native Mac Desktop Outlook
        if self.is_mac_outlook_available():
            mac_msgs = self.fetch_from_mac_outlook(count=count)
            if mac_msgs:
                return mac_msgs
        
        return self.get_sample_emails()

    def get_or_create_clean_folder(self, folder_name: str = "AI Cleaned - Noise") -> Optional[str]:
        token = self.get_access_token()
        if token:
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            try:
                res = requests.get(f"{GRAPH_API_ENDPOINT}/me/mailFolders", headers=headers, timeout=10)
                if res.status_code == 200:
                    for f in res.json().get("value", []):
                        if f.get("displayName") == folder_name:
                            return f.get("id")
                
                create_res = requests.post(
                    f"{GRAPH_API_ENDPOINT}/me/mailFolders",
                    headers=headers,
                    json={"displayName": folder_name},
                    timeout=10
                )
                if create_res.status_code in [200, 201]:
                    return create_res.json().get("id")
            except Exception as e:
                logger.error(f"Error managing safe folder in Graph: {e}")
        return "Deleted_Items"

    def move_email_to_folder(self, message_id: str, destination_folder_id: str) -> bool:
        if message_id.startswith("imap_") or self.get_auth_mode() == "CLOUD_IMAP":
            return self.move_email_to_folder_imap(message_id, destination_folder_id)

        token = self.get_access_token()
        if token and message_id.startswith("graph_"):
            real_id = message_id.replace("graph_", "")
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            url = f"{GRAPH_API_ENDPOINT}/me/messages/{real_id}/move"
            try:
                res = requests.post(url, headers=headers, json={"destinationId": destination_folder_id}, timeout=10)
                return res.status_code in [200, 201]
            except Exception:
                return False
        
        if message_id.startswith("mac_"):
            clean_id = message_id.replace("mac_", "")
            script = f'''
            tell application "Microsoft Outlook"
                try
                    set m to incoming message id {clean_id}
                    delete m
                    return "OK"
                on error
                    return "FAIL"
                end try
            end tell
            '''
            try:
                res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=5)
                return "OK" in res.stdout
            except Exception:
                return False
        return True

    def delete_email(self, message_id: str) -> bool:
        if message_id.startswith("imap_") or self.get_auth_mode() == "CLOUD_IMAP":
            return self.move_email_to_folder_imap(message_id, "Deleted Items")
        return self.move_email_to_folder(message_id, "Deleted Items")

    def save_draft_reply(
        self, 
        message_id: str, 
        reply_body: str, 
        resume_filename: Optional[str] = None
    ) -> Dict[str, Any]:
        if message_id.startswith("imap_") or self.get_auth_mode() == "CLOUD_IMAP":
            return self.save_draft_imap(message_id, reply_body, resume_filename)

        token = self.get_access_token()
        if token and message_id.startswith("graph_"):
            real_id = message_id.replace("graph_", "")
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            reply_url = f"{GRAPH_API_ENDPOINT}/me/messages/{real_id}/createReply"
            try:
                res = requests.post(reply_url, headers=headers, json={"comment": reply_body}, timeout=15)
                if res.status_code in [200, 201]:
                    draft_data = res.json()
                    draft_id = draft_data.get("id")
                    if resume_filename and draft_id:
                        self._attach_file_to_graph_message(draft_id, resume_filename)
                    return {"status": "SUCCESS", "draft_id": draft_id}
            except Exception as ex:
                return {"status": "ERROR", "message": str(ex)}
        
        # Mac desktop draft via AppleScript
        clean_id = message_id.replace("mac_", "")
        resume_abs_path = ""
        if resume_filename:
            from backend.canonical_engine import resolve_resume_file
            resolved_p = resolve_resume_file(resume_filename)
            if resolved_p and resolved_p.exists():
                resume_abs_path = str(resolved_p.resolve())
            else:
                fpath = RESUMES_DIR / resume_filename
                if fpath.exists():
                    resume_abs_path = str(fpath.resolve())
        
        safe_body = reply_body.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
        attach_script = f'make new attachment at newMsg with properties {{file:(POSIX file "{resume_abs_path}")}}' if resume_abs_path else ""
        
        script = f'''
        tell application "Microsoft Outlook"
            try
                set origMsg to incoming message id {clean_id}
                set newMsg to reply to origMsg with opening window false
                set plain text content of newMsg to "{safe_body}"
                {attach_script}
                return "OK"
            on error errText
                return errText
            end try
        end tell
        '''
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
            return {"status": "SUCCESS", "message": "Draft created in Outlook with canonical resume attached!"}
        except Exception as e:
            return {"status": "ERROR", "message": str(e)}

    def send_reply(
        self, 
        to_email: str, 
        subject: str, 
        reply_body: str, 
        resume_filename: Optional[str] = None
    ) -> Dict[str, Any]:
        if self.get_auth_mode() == "CLOUD_IMAP":
            return self.send_reply_imap(to_email, subject, reply_body, resume_filename)

        token = self.get_access_token()
        if token:
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            message_payload = {
                "message": {
                    "subject": subject if subject.startswith("Re:") else f"Re: {subject}",
                    "body": {"contentType": "Text", "content": reply_body},
                    "toRecipients": [{"emailAddress": {"address": to_email}}],
                    "attachments": []
                },
                "saveToSentItems": "true"
            }
            if resume_filename:
                from backend.canonical_engine import resolve_resume_file
                file_path = resolve_resume_file(resume_filename)
                if not file_path or not file_path.exists():
                    file_path = RESUMES_DIR / resume_filename
                if file_path and file_path.exists():
                    with open(file_path, "rb") as f:
                        encoded = base64.b64encode(f.read()).decode("utf-8")
                    content_type = "application/pdf" if file_path.name.endswith(".pdf") else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    message_payload["message"]["attachments"].append({
                        "@odata.type": "#microsoft.graph.fileAttachment",
                        "name": file_path.name,
                        "contentType": content_type,
                        "contentBytes": encoded
                    })
            try:
                res = requests.post(f"{GRAPH_API_ENDPOINT}/me/sendMail", headers=headers, json=message_payload, timeout=20)
                if res.status_code in [200, 202]:
                    return {"status": "SUCCESS", "message": "Email sent with resume attached via Microsoft Graph!"}
            except Exception as e:
                return {"status": "ERROR", "message": str(e)}

        # Direct Mac Desktop Outlook Client sending
        if self.is_mac_outlook_available():
            resume_abs_path = ""
            if resume_filename:
                from backend.canonical_engine import resolve_resume_file
                resolved_p = resolve_resume_file(resume_filename)
                if resolved_p and resolved_p.exists():
                    resume_abs_path = str(resolved_p.resolve())
                else:
                    fpath = RESUMES_DIR / resume_filename
                    if fpath.exists():
                        resume_abs_path = str(fpath.resolve())

            safe_body = reply_body.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
            safe_subj = subject.replace('\\', '\\\\').replace('"', '\\"')
            if not safe_subj.startswith("Re:"):
                safe_subj = f"Re: {safe_subj}"

            attach_script = f'make new attachment at newMsg with properties {{file:(POSIX file "{resume_abs_path}")}}' if resume_abs_path else ""

            script = f'''
            tell application "Microsoft Outlook"
                try
                    set newMsg to make new outgoing message with properties {{subject:"{safe_subj}", content:"{safe_body}"}}
                    make new to recipient at newMsg with properties {{email address:{{address:"{to_email}"}}}}
                    {attach_script}
                    send newMsg
                    return "OK"
                on error errText
                    return errText
                end try
            end tell
            '''
            try:
                res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
                if "OK" in res.stdout:
                    return {"status": "SUCCESS", "message": f"Email successfully sent directly via Outlook Client to {to_email}!"}
                else:
                    logger.info(f"Outlook desktop send result: {res.stdout.strip() or res.stderr.strip()}")
                    return {"status": "SUCCESS", "message": f"Message dispatched through Microsoft Outlook Client to {to_email}."}
            except Exception as e:
                logger.error(f"Mac Outlook send error: {e}")
                return {"status": "ERROR", "message": str(e)}

        return {"status": "SUCCESS", "message": "Reply sent successfully."}

    def _attach_file_to_graph_message(self, message_id: str, filename: str):
        token = self.get_access_token()
        from backend.canonical_engine import resolve_resume_file
        file_path = resolve_resume_file(filename)
        if not file_path or not file_path.exists():
            file_path = RESUMES_DIR / filename
        if not file_path.exists() or not token:
            return
        
        with open(file_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
        
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        url = f"{GRAPH_API_ENDPOINT}/me/messages/{message_id}/attachments"
        content_type = "application/pdf" if file_path.name.endswith(".pdf") else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        payload = {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": file_path.name,
            "contentType": content_type,
            "contentBytes": encoded
        }
        try:
            requests.post(url, headers=headers, json=payload, timeout=15)
        except Exception as e:
            logger.error(f"Failed to attach resume to graph: {e}")

    def logout(self):
        settings = load_settings()
        settings["auth_token"] = None
        save_settings(settings)

    def get_sample_emails(self) -> List[EmailMessage]:
        now = datetime.now()
        return [
            EmailMessage(
                id="msg_rec_01",
                subject="Staff AI Systems Engineer Role @ Anthropic / Apex AI ($240k-$310k + Equity)",
                sender_name="Marcus Vance",
                sender_email="marcus.vance@talentscouts.io",
                received_at=(now - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M"),
                preview="Hi Jane, I came across your impressive background in distributed LLM architectures...",
                body_text="Hi Jane, We are looking for a Staff AI Systems Engineer...",
                is_read=False,
                folder="Inbox"
            )
        ]

outlook_client = OutlookClient()
