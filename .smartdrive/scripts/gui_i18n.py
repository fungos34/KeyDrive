#!/usr/bin/env python3
"""
GUI Internationalization (i18n) Module

SINGLE SOURCE OF TRUTH for all GUI-visible text labels.
All GUI strings MUST be defined here and accessed via tr() function.

Per AGENT_ARCHITECTURE.md Section 11.2:
- NO GUI text literals outside this module
- ALL labels/buttons/messages use tr(key)
- Fallback: missing key in selected lang -> try 'en' -> fail loudly
"""

from typing import Dict

# =============================================================================
# Available Languages
# =============================================================================

AVAILABLE_LANGUAGES: Dict[str, str] = {
    "en": "English",
    "de": "Deutsch",
    "bs": "Bosanski",
    "es": "Español",
    "fr": "Français",
    "ru": "Русский",
    "zh": "中文",
}

# =============================================================================
# Translation Table
# =============================================================================

TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "en": {
        # Window titles
        "window_title": "KeyDrive",
        "settings_window_title": "Settings",
        
        # Button labels
        "btn_mount": "🔓 Mount",
        "btn_unmount": "🔒 Unmount",
        "btn_cancel_auth": "❌ Cancel",
        "btn_confirm_mount": "✅ Confirm",
        "btn_tools": "⚙️",
        "btn_close": "✕",
        "btn_save": "Save",
        "btn_cancel": "Cancel",
        
        # Status messages
        "status_config_not_found": "Configuration not found",
        "status_volume_mounted": "Volume mounted",
        "status_volume_not_mounted": "Volume not mounted",
        "status_mounting": "⏳ Mounting volume...",
        "status_mounting_gpg": "⏳ Mounting volume (GPG authentication)...",
        "status_unmounting": "⏳ Unmounting volume...",
        "status_mount_success": "✅ Volume mounted successfully",
        "status_mount_failed": "❌ Mount failed",
        "status_unmount_success": "✅ Volume unmounted successfully",
        "status_unmount_failed": "❌ Unmount failed",
        
        # Info labels
        "info_unavailable": "Info unavailable",
        "keyfile_selected_one": "1 keyfile selected",
        "keyfile_selected_many": "{count} keyfiles selected",
        "keyfile_drop_hint": "Drop keyfiles here or click to browse",
        "keyfile_drop_supports_multiple": "Supports multiple keyfiles",
        "label_show_password": "Show password",
        
        # Size formatting
        "size_free": "Free: {size}",
        
        # Icons/placeholders
        "icon_drive": "🚀",
        
        # Tooltips
        "tooltip_exit": "Exit SmartDrive",
        "tooltip_settings": "Advanced tools and settings",
        
        # Labels
        "label_product_name": "Product Name",
        "label_preview": "Preview:",
        "label_password": "Password:",
        "label_keyfile": "Keyfile:",
        "label_hardware_key_hint": "💡 Hardware key may be required for authentication",
        "label_forgot_password": "Forgot your password?",
        
        # Placeholder text
        "placeholder_password": "Enter your VeraCrypt password...",
        
        # Menu items
        "menu_settings": "⚙️ Settings",
        "menu_rekey": "🔑 Change Password/Keyfile",
        "menu_update": "⬇️ Update Scripts",
        "menu_recovery": "💾 Recovery Kit",
        "menu_about": "ℹ️ About",
        "menu_cli": "💻 Open CLI",
        "menu_clear_keyfiles": "Clear Keyfiles",
        "dialog_select_keyfiles": "Select Keyfile(s)",
        
        # Tray messages
        "tray_minimized_message": "Running in background. Click tray icon to restore.",
        "tray_tooltip": "{name} ({id})",
        
        # Worker messages (keys for structured errors)
        "worker_mount_script_not_found": "Mount script not found",
        "worker_mount_success": "Volume mounted successfully",
        "worker_mount_failed": "Mount failed: {error}",
        "worker_mount_timeout": "Mount operation timed out",
        "worker_mount_error": "Mount error: {error}",
        "worker_unmount_script_not_found": "Unmount script not found",
        "worker_unmount_success": "Volume unmounted successfully",
        "worker_unmount_failed": "Unmount failed: {error}",
        "worker_unmount_timeout": "Unmount operation timed out",
        "worker_unmount_error": "Unmount error: {error}",
        
        # Settings dialog - Tab names
        "settings_language": "Language",
        "settings_general": "General",
        "settings_security": "Security",
        "settings_keyfile": "Keyfile",
        "settings_windows": "Windows",
        "settings_unix": "Unix",
        "settings_updates": "Updates",
        "settings_recovery": "Recovery",
        "settings_lost_and_found": "Lost & Found",
        "settings_advanced": "Advanced",
        
        # Settings dialog - Tab descriptions
        "settings_general_desc": "Configure display name, language, and theme preferences for the application.",
        "settings_security_desc": "Set the encryption mode and authentication method for your secure drive.",
        "settings_keyfile_desc": "Manage keyfile paths for encryption and GPG-protected authentication.",
        "settings_windows_desc": "Windows-specific settings including mount drive letter and VeraCrypt location.",
        "settings_unix_desc": "Linux and macOS settings including mount point directory.",
        "settings_updates_desc": "Configure automatic update checking and server settings.",
        "settings_recovery_desc": "Set up Shamir Secret Sharing recovery options to recover access if keys are lost.",
        "settings_lost_and_found_desc": "Display a contact message on the drive for recovery if lost.",
        "settings_advanced_desc": "Technical settings for encryption parameters and integrity verification.",
        
        "settings_restart_not_required": "✓ Changes applied immediately (no restart required)",
        "label_mode": "Mode",
        "label_encrypted_keyfile": "Encrypted keyfile",
        "label_volume_path": "Volume path",
        "label_mount_letter": "Mount letter",
        "label_veracrypt_path": "VeraCrypt path",
        "label_mount_point": "Mount point",
        "label_source_type": "Source type",
        "label_server_url": "Server URL",
        "label_local_root": "Local root",
        "error_invalid_mount_letter": "Mount letter must be a single A–Z character.",
        "error_save_failed": "Could not save config.json:",
        "title_invalid_mount_letter": "Invalid Mount Letter",
        "title_save_failed": "Save Failed",
        
        # Settings dialog - Additional fields (schema-driven UI)
        "label_drive_id": "Drive ID",
        "label_drive_name": "Drive Name",
        "label_setup_date": "Setup Date",
        "label_last_password_change": "Last Password Change",
        "label_last_verified": "Last Verified",
        "label_plain_keyfile": "Plain Keyfile",
        "label_seed_gpg_path": "GPG Seed File",
        "label_kdf": "Key Derivation Function",
        "label_pw_encoding": "Password Encoding",
        "label_recovery_enabled": "Enable Recovery Kit",
        "label_recovery_share_count": "Recovery Share Count",
        "label_recovery_threshold": "Recovery Threshold",
        "label_lost_and_found_enabled": "Enable Lost & Found",
        "label_lost_and_found_message": "Return Message",
        "label_verification_overridden": "Override Verification",
        "label_integrity_signed": "Integrity Signed",
        "label_signing_key_fpr": "Signing Key Fingerprint",
        "label_salt_b64": "Salt (Base64)",
        "label_hkdf_info": "HKDF Info",
        "label_schema_version": "Schema Version",
        "label_version": "Version",
        
        # Tooltips for settings fields
        "tooltip_drive_id": "Unique identifier for this drive (read-only)",
        "tooltip_drive_name": "Custom name for this drive",
        "tooltip_language": "User interface language",
        "tooltip_theme": "Color scheme for the interface",
        "tooltip_mode": "Security mode: password-only, keyfile, or YubiKey/GPG",
        "tooltip_encrypted_keyfile": "Path to GPG-encrypted keyfile (for GPG modes)",
        "tooltip_plain_keyfile": "Path to unencrypted keyfile (for plain keyfile mode)",
        "tooltip_seed_gpg_path": "Path to GPG seed file for password derivation",
        "tooltip_kdf": "Key derivation function for GPG password mode",
        "tooltip_pw_encoding": "Character encoding for password (UTF-8 recommended)",
        "tooltip_windows_volume_path": "Windows volume GUID or device path",
        "tooltip_mount_letter": "Drive letter to mount as (A-Z)",
        "tooltip_veracrypt_path": "Path to VeraCrypt.exe executable",
        "tooltip_unix_volume_path": "Unix device path (e.g., /dev/sdb2)",
        "tooltip_mount_point": "Unix mount point directory",
        "tooltip_recovery_enabled": "Enable emergency recovery kit generation",
        "tooltip_recovery_share_count": "Number of recovery shares to generate",
        "tooltip_recovery_threshold": "Minimum shares needed for recovery",
        "tooltip_lost_and_found_enabled": "Enable return message if drive is lost",
        "tooltip_lost_and_found_message": "Message displayed if drive is found",
        "tooltip_source_type": "Update source: local directory or server URL",
        "tooltip_server_url": "Server URL for updates",
        "tooltip_local_root": "Local directory containing update files",
        "tooltip_verification_overridden": "Bypass integrity verification (dangerous!)",
        "tooltip_integrity_signed": "Drive integrity has been cryptographically signed",
        "tooltip_signing_key_fpr": "GPG key fingerprint used for signing",
        "tooltip_salt_b64": "Cryptographic salt for key derivation",
        "tooltip_hkdf_info": "Context string for HKDF key derivation",
        
        # Popup dialogs
        "popup_keyfile_required_title": "Keyfile Required",
        "popup_keyfile_required_body": "Please select a keyfile for password + keyfile mode.",
        "popup_password_required_title": "Password Required",
        "popup_password_required_body": "Please enter your VeraCrypt password.",
        "popup_recovery_title": "Password Recovery",
        "popup_recovery_available_body": "Recovery kit is available for this drive!\n\nTo recover access to your encrypted volume:\n\n1. Use the SmartDrive CLI: python smartdrive.py\n2. Select option 6: Recovery Kit\n3. Follow the recovery instructions\n\nOr contact your system administrator.",
        "popup_recovery_unavailable_body": "No recovery kit is currently available for this drive.\n\nTo set up password recovery:\n\n1. Use the SmartDrive CLI: python smartdrive.py\n2. Select option 6: Recovery Kit\n3. Choose 'Generate Recovery Kit'\n\nOr contact your system administrator.",
        
        # Recovery tab - Phrase input and recovery actions
        "recovery_section_title": "🔐 Emergency Recovery",
        "recovery_instructions": "Enter your 24-word recovery phrase to recover access to your encrypted volume. You can also provide a recovery container file if you have one.",
        "label_recovery_phrase": "Recovery Phrase (24 words):",
        "placeholder_recovery_phrase": "Enter 24 words separated by spaces...",
        "label_recovery_container": "Recovery Container (optional):",
        "btn_browse_container": "Browse...",
        "btn_recover_credentials": "🔓 Recover Credentials",
        "recovery_status_ready": "Enter your recovery phrase and click 'Recover Credentials'",
        "recovery_status_validating": "Validating recovery phrase...",
        "recovery_status_decrypting": "Decrypting recovery container...",
        "recovery_status_success": "✅ Recovery successful! Credentials recovered.",
        "recovery_status_failed": "❌ Recovery failed: {error}",
        "recovery_result_title": "Recovered Credentials",
        "recovery_result_password": "Password:",
        "recovery_result_keyfile": "Keyfile:",
        "recovery_result_mode": "Security Mode:",
        "recovery_result_copy_password": "📋 Copy Password",
        "recovery_result_save_keyfile": "💾 Save Keyfile",
        "recovery_copied_to_clipboard": "Password copied to clipboard (auto-clears in 30 seconds)",
        "recovery_keyfile_saved": "Keyfile saved to: {path}",
        "recovery_phrase_invalid": "Invalid recovery phrase. Please check all 24 words.",
        "recovery_container_not_found": "Recovery container not found. Please select the container file.",
        "recovery_no_kit_configured": "No recovery kit is configured for this drive.",
        "recovery_generate_first": "Please generate a recovery kit first using Settings or CLI.",
        
        "popup_unmount_failed_title": "Unmount Failed",
        "popup_mount_failed_title": "Mount Failed",
        "popup_update_not_possible_title": "Update Not Possible",
        "popup_update_confirm_title": "Confirm Update",
        "popup_update_confirm_message": "About to run UPDATE ({direction}).\n\nFROM:\n  {src_root}\n\nTO:\n  {dst_root}\n\nItems:\n  - {items}\n\nMethod: {method}\n\nThis will overwrite existing files. Continue?",
        "popup_update_config_title": "Update Configuration",
        "popup_update_config_body": "Update source is not configured. Please set it in Settings.",
        "popup_update_complete_title": "Update Complete",
        "popup_update_complete_body": "Update finished successfully. Please restart the application.",
        "popup_update_failed_title": "Update Failed",
        "popup_update_failed_body": "Update failed:\n\n{error}",
        "popup_update_timeout_title": "Update Timeout",
        "popup_update_timeout_body": "Update did not complete within 120 seconds.",
        "popup_update_error_title": "Update Error",
        "popup_update_error_body": "Failed to run update:\n\n{error}",
        "popup_cli_failed_title": "CLI Launch Failed",
        "popup_cli_failed_body": "Could not open CLI:\n\n{error}",
        
        # Update configuration error messages
        "error_update_server_url_not_configured": "Server URL is not configured.\\n\\nGo to Settings to configure the update URL.",
        "error_update_local_root_not_configured": "Local update directory is not configured.\\n\\nGo to Settings to configure the local update root.",
        "error_update_local_root_not_found": "Local update directory not found:\\n\\n{path}\\n\\nCheck Settings to verify the path.",
        "error_update_install_dir_not_found": "Installation directory not found:\\n\\n{path}",
        "error_update_unknown_source_type": "Unknown update source type: {type}",
        
        # Hardware key error messages
        "error_hardware_key_missing_title": "Hardware Key Required",
        "error_hardware_key_missing_body": "Hardware key (YubiKey/GPG card) not detected. Please insert your hardware key and try again.",
        
        # Theme names (for theme dropdown)
        "theme_green": "Green (Default)",
        "theme_blue": "Blue",
        "theme_rose": "Rose",
        "theme_slate": "Slate",
        "label_theme": "Theme",
        
        # File explorer buttons
        "tooltip_open_launcher_drive": "Open launcher drive",
        "tooltip_open_mounted_volume": "Open mounted volume",
        "popup_open_failed_title": "Open Failed",
        "popup_open_failed_body": "Could not open file explorer:\n\n{path}\n\n{error}",
    },
    "de": {
        # Window titles
        "window_title": "KeyDrive",
        "settings_window_title": "Einstellungen",
        
        # Button labels
        "btn_mount": "🔓 Einbinden",
        "btn_unmount": "🔒 Aushängen",
        "btn_cancel_auth": "❌ Abbrechen",
        "btn_confirm_mount": "✅ Bestätigen",
        "btn_tools": "⚙️",
        "btn_close": "✕",
        "btn_save": "Speichern",
        "btn_cancel": "Abbrechen",
        
        # Status messages
        "status_config_not_found": "Konfiguration nicht gefunden",
        "status_volume_mounted": "Volume eingebunden",
        "status_volume_not_mounted": "Volume nicht eingebunden",
        "status_mounting": "⏳ Volume wird eingebunden...",
        "status_mounting_gpg": "⏳ Volume wird eingebunden (GPG-Authentifizierung)...",
        "status_unmounting": "⏳ Volume wird ausgehängt...",
        "status_mount_success": "✅ Volume erfolgreich eingebunden",
        "status_mount_failed": "❌ Einbinden fehlgeschlagen",
        "status_unmount_success": "✅ Volume erfolgreich ausgehängt",
        "status_unmount_failed": "❌ Aushängen fehlgeschlagen",
        
        # Info labels
        "info_unavailable": "Info nicht verfügbar",
        "keyfile_selected_one": "1 Schlüsseldatei ausgewählt",
        "keyfile_selected_many": "{count} Schlüsseldateien ausgewählt",
        "keyfile_drop_hint": "Schlüsseldateien hier ablegen oder klicken zum Auswählen",
        "keyfile_drop_supports_multiple": "Unterstützt mehrere Schlüsseldateien",
        "label_show_password": "Passwort anzeigen",
        
        # Size formatting
        "size_free": "Frei: {size}",
        
        # Icons/placeholders
        "icon_drive": "🚀",
        
        # Tooltips
        "tooltip_exit": "SmartDrive beenden",
        "tooltip_settings": "Erweiterte Werkzeuge und Einstellungen",
        
        # Labels
        "label_product_name": "Produktname",
        "label_preview": "Vorschau:",
        "label_password": "Passwort:",
        "label_keyfile": "Schlüsseldatei:",
        "label_hardware_key_hint": "💡 Hardware-Schlüssel kann für Authentifizierung erforderlich sein",
        "label_forgot_password": "Passwort vergessen?",
        
        # Placeholder text
        "placeholder_password": "Geben Sie Ihr VeraCrypt-Passwort ein...",
        
        # Menu items
        "menu_settings": "⚙️ Einstellungen",
        "menu_rekey": "🔑 Passwort/Schlüssel ändern",
        "menu_update": "⬇️ Skripte aktualisieren",
        "menu_recovery": "💾 Wiederherstellungs-Kit",
        "menu_about": "ℹ️ Über",
        "menu_cli": "💻 CLI öffnen",
        "menu_clear_keyfiles": "Schlüsseldateien löschen",
        "dialog_select_keyfiles": "Schlüsseldatei(en) auswählen",
        
        # Tray messages
        "tray_minimized_message": "Läuft im Hintergrund. Klicken Sie auf das Tray-Symbol zum Wiederherstellen.",
        "tray_tooltip": "{name} ({id})",
        
        # Worker messages (keys for structured errors)
        "worker_mount_script_not_found": "Mount-Skript nicht gefunden",
        "worker_mount_success": "Volume erfolgreich eingebunden",
        "worker_mount_failed": "Einbinden fehlgeschlagen: {error}",
        "worker_mount_timeout": "Mount-Vorgang zeitüberschreitung",
        "worker_mount_error": "Mount-Fehler: {error}",
        "worker_unmount_script_not_found": "Unmount-Skript nicht gefunden",
        "worker_unmount_success": "Volume erfolgreich ausgehängt",
        "worker_unmount_failed": "Aushängen fehlgeschlagen: {error}",
        "worker_unmount_timeout": "Unmount-Vorgang Zeitüberschreitung",
        "worker_unmount_error": "Unmount-Fehler: {error}",
        
        # Settings dialog - Tab names
        "settings_language": "Sprache",
        "settings_general": "Allgemein",
        "settings_security": "Sicherheit",
        "settings_keyfile": "Schlüsseldatei",
        "settings_windows": "Windows",
        "settings_unix": "Unix",
        "settings_updates": "Aktualisierungen",
        "settings_recovery": "Wiederherstellung",
        "settings_lost_and_found": "Fundsachen",
        "settings_advanced": "Erweitert",
        
        # Settings dialog - Tab descriptions
        "settings_general_desc": "Konfigurieren Sie Anzeigename, Sprache und Design-Einstellungen.",
        "settings_security_desc": "Verschlüsselungsmodus und Authentifizierungsmethode für Ihr sicheres Laufwerk.",
        "settings_keyfile_desc": "Verwalten Sie Schlüsseldatei-Pfade für Verschlüsselung und GPG-Authentifizierung.",
        "settings_windows_desc": "Windows-spezifische Einstellungen inkl. Laufwerksbuchstabe und VeraCrypt-Pfad.",
        "settings_unix_desc": "Linux- und macOS-Einstellungen inkl. Einhängepunkt-Verzeichnis.",
        "settings_updates_desc": "Automatische Update-Prüfung und Server-Einstellungen konfigurieren.",
        "settings_recovery_desc": "Shamir Secret Sharing Wiederherstellungsoptionen für Notfallzugriff einrichten.",
        "settings_lost_and_found_desc": "Kontaktnachricht auf dem Laufwerk für Rückgabe bei Verlust anzeigen.",
        "settings_advanced_desc": "Technische Einstellungen für Verschlüsselungsparameter und Integritätsprüfung.",
        
        "settings_restart_not_required": "✓ Änderungen sofort übernommen (kein Neustart erforderlich)",
        "label_mode": "Modus",
        "label_encrypted_keyfile": "Verschlüsselte Schlüsseldatei",
        "label_volume_path": "Volume-Pfad",
        "label_mount_letter": "Laufwerksbuchstabe",
        "label_veracrypt_path": "VeraCrypt-Pfad",
        "label_mount_point": "Einhängepunkt",
        "label_source_type": "Quellentyp",
        "label_server_url": "Server-URL",
        "label_local_root": "Lokaler Pfad",
        "error_invalid_mount_letter": "Laufwerksbuchstabe muss ein einzelnes Zeichen von A–Z sein.",
        "error_save_failed": "Konnte config.json nicht speichern:",
        "title_invalid_mount_letter": "Ungültiger Laufwerksbuchstabe",
        "title_save_failed": "Speichern fehlgeschlagen",
        
        # Popup dialogs
        "popup_keyfile_required_title": "Schlüsseldatei erforderlich",
        "popup_keyfile_required_body": "Bitte wählen Sie eine Schlüsseldatei für den Passwort + Schlüsseldatei-Modus.",
        "popup_password_required_title": "Passwort erforderlich",
        "popup_password_required_body": "Bitte geben Sie Ihr VeraCrypt-Passwort ein.",
        "popup_recovery_title": "Passwort-Wiederherstellung",
        "popup_recovery_available_body": "Wiederherstellungs-Kit ist für dieses Laufwerk verfügbar!\n\nUm Zugriff auf Ihr verschlüsseltes Volume wiederherzustellen:\n\n1. Verwenden Sie die SmartDrive CLI: python smartdrive.py\n2. Wählen Sie Option 6: Recovery Kit\n3. Folgen Sie den Wiederherstellungsanweisungen\n\nOder kontaktieren Sie Ihren Systemadministrator.",
        "popup_recovery_unavailable_body": "Kein Wiederherstellungs-Kit ist derzeit für dieses Laufwerk verfügbar.\n\nUm Passwort-Wiederherstellung einzurichten:\n\n1. Verwenden Sie die SmartDrive CLI: python smartdrive.py\n2. Wählen Sie Option 6: Recovery Kit\n3. Wählen Sie 'Wiederherstellungs-Kit generieren'\n\nOder kontaktieren Sie Ihren Systemadministrator.",
        
        # Recovery tab - Phrase input and recovery actions
        "recovery_section_title": "🔐 Notfall-Wiederherstellung",
        "recovery_instructions": "Geben Sie Ihre 24-Wort-Wiederherstellungsphrase ein, um Zugriff auf Ihr verschlüsseltes Volume wiederherzustellen. Sie können auch eine Wiederherstellungs-Container-Datei angeben, falls vorhanden.",
        "label_recovery_phrase": "Wiederherstellungsphrase (24 Wörter):",
        "placeholder_recovery_phrase": "Geben Sie 24 Wörter durch Leerzeichen getrennt ein...",
        "label_recovery_container": "Wiederherstellungs-Container (optional):",
        "btn_browse_container": "Durchsuchen...",
        "btn_recover_credentials": "🔓 Zugangsdaten wiederherstellen",
        "recovery_status_ready": "Geben Sie Ihre Wiederherstellungsphrase ein und klicken Sie auf 'Zugangsdaten wiederherstellen'",
        "recovery_status_validating": "Validiere Wiederherstellungsphrase...",
        "recovery_status_decrypting": "Entschlüssele Wiederherstellungs-Container...",
        "recovery_status_success": "✅ Wiederherstellung erfolgreich! Zugangsdaten wiederhergestellt.",
        "recovery_status_failed": "❌ Wiederherstellung fehlgeschlagen: {error}",
        "recovery_result_title": "Wiederhergestellte Zugangsdaten",
        "recovery_result_password": "Passwort:",
        "recovery_result_keyfile": "Schlüsseldatei:",
        "recovery_result_mode": "Sicherheitsmodus:",
        "recovery_result_copy_password": "📋 Passwort kopieren",
        "recovery_result_save_keyfile": "💾 Schlüsseldatei speichern",
        "recovery_copied_to_clipboard": "Passwort in Zwischenablage kopiert (wird in 30 Sekunden gelöscht)",
        "recovery_keyfile_saved": "Schlüsseldatei gespeichert unter: {path}",
        "recovery_phrase_invalid": "Ungültige Wiederherstellungsphrase. Bitte überprüfen Sie alle 24 Wörter.",
        "recovery_container_not_found": "Wiederherstellungs-Container nicht gefunden. Bitte wählen Sie die Container-Datei aus.",
        "recovery_no_kit_configured": "Kein Wiederherstellungs-Kit für dieses Laufwerk konfiguriert.",
        "recovery_generate_first": "Bitte generieren Sie zuerst ein Wiederherstellungs-Kit über Einstellungen oder CLI.",
        
        "popup_unmount_failed_title": "Aushängen fehlgeschlagen",
        "popup_mount_failed_title": "Einbinden fehlgeschlagen",
        "popup_update_not_possible_title": "Update nicht möglich",
        "popup_update_confirm_title": "Update bestätigen",
        "popup_update_confirm_message": "UPDATE ({direction}) wird ausgeführt.\n\nVON:\n  {src_root}\n\nNACH:\n  {dst_root}\n\nElemente:\n  - {items}\n\nMethode: {method}\n\nDies überschreibt vorhandene Dateien. Fortfahren?",
        "popup_update_config_title": "Update-Konfiguration",
        "popup_update_config_body": "Update-Quelle ist nicht konfiguriert. Bitte in Einstellungen festlegen.",
        "popup_update_complete_title": "Update abgeschlossen",
        "popup_update_complete_body": "Update erfolgreich abgeschlossen. Bitte Anwendung neu starten.",
        "popup_update_failed_title": "Update fehlgeschlagen",
        "popup_update_failed_body": "Update fehlgeschlagen:\n\n{error}",
        "popup_update_timeout_title": "Update-Zeitüberschreitung",
        "popup_update_timeout_body": "Update wurde nicht innerhalb von 120 Sekunden abgeschlossen.",
        "popup_update_error_title": "Update-Fehler",
        "popup_update_error_body": "Update konnte nicht ausgeführt werden:\n\n{error}",
        "popup_cli_failed_title": "CLI-Start fehlgeschlagen",
        "popup_cli_failed_body": "CLI konnte nicht geöffnet werden:\n\n{error}",
        
        # Update configuration error messages
        "error_update_server_url_not_configured": "Server-URL ist nicht konfiguriert.\\n\\nGehen Sie zu Einstellungen, um die Update-URL zu konfigurieren.",
        "error_update_local_root_not_configured": "Lokales Update-Verzeichnis ist nicht konfiguriert.\\n\\nGehen Sie zu Einstellungen, um das lokale Update-Root zu konfigurieren.",
        "error_update_local_root_not_found": "Lokales Update-Verzeichnis nicht gefunden:\\n\\n{path}\\n\\nÜberprüfen Sie die Einstellungen, um den Pfad zu verifizieren.",
        "error_update_install_dir_not_found": "Installationsverzeichnis nicht gefunden:\\n\\n{path}",
        "error_update_unknown_source_type": "Unbekannter Update-Quelltyp: {type}",
        
        # Hardware key error messages
        "error_hardware_key_missing_title": "Hardware-Schlüssel erforderlich",
        "error_hardware_key_missing_body": "Hardware-Schlüssel (YubiKey/GPG-Karte) nicht erkannt. Bitte stecken Sie Ihren Hardware-Schlüssel ein und versuchen Sie es erneut.",
        
        # Theme names (for theme dropdown)
        "theme_green": "Grün (Standard)",
        "theme_blue": "Blau",
        "theme_rose": "Rosa",
        "theme_slate": "Schiefer",
        "label_theme": "Thema",
        
        # File explorer buttons
        "tooltip_open_launcher_drive": "Launcher-Laufwerk öffnen",
        "tooltip_open_mounted_volume": "Eingebundenes Volume öffnen",
        "popup_open_failed_title": "Öffnen fehlgeschlagen",
        "popup_open_failed_body": "Dateimanager konnte nicht geöffnet werden:\n\n{path}\n\n{error}",
        
        # Settings dialog - Additional fields (schema-driven UI)
        "label_drive_id": "Laufwerk-ID",
        "label_drive_name": "Laufwerksname",
        "label_setup_date": "Einrichtungsdatum",
        "label_last_password_change": "Letzte Passwortänderung",
        "label_last_verified": "Zuletzt überprüft",
        "label_plain_keyfile": "Einfache Schlüsseldatei",
        "label_seed_gpg_path": "GPG-Seed-Datei",
        "label_kdf": "Schlüsselableitungsfunktion",
        "label_pw_encoding": "Passwort-Kodierung",
        "label_recovery_enabled": "Wiederherstellungs-Kit aktivieren",
        "label_recovery_share_count": "Anzahl Wiederherstellungsanteile",
        "label_recovery_threshold": "Wiederherstellungsschwelle",
        "label_lost_and_found_enabled": "Fundmeldung aktivieren",
        "label_lost_and_found_message": "Rückgabenachricht",
        "label_verification_overridden": "Überprüfung überschrieben",
        "label_integrity_signed": "Integrität signiert",
        "label_signing_key_fpr": "Signaturschlüssel-Fingerabdruck",
        "label_salt_b64": "Salt (Base64)",
        "label_hkdf_info": "HKDF-Info",
        "label_schema_version": "Schema-Version",
        "label_version": "Version",
        
        # Tooltips for settings fields
        "tooltip_drive_id": "Eindeutige Kennung für dieses Laufwerk (schreibgeschützt)",
        "tooltip_drive_name": "Benutzerdefinierter Name für dieses Laufwerk",
        "tooltip_language": "Sprache der Benutzeroberfläche",
        "tooltip_theme": "Farbschema für die Oberfläche",
        "tooltip_mode": "Sicherheitsmodus: nur Passwort, Schlüsseldatei oder YubiKey/GPG",
        "tooltip_encrypted_keyfile": "Pfad zur GPG-verschlüsselten Schlüsseldatei (für GPG-Modi)",
        "tooltip_plain_keyfile": "Pfad zur unverschlüsselten Schlüsseldatei (für einfachen Schlüsseldatei-Modus)",
        "tooltip_seed_gpg_path": "Pfad zur GPG-Seed-Datei für Passwortableitung",
        "tooltip_kdf": "Schlüsselableitungsfunktion für GPG-Passwortmodus",
        "tooltip_pw_encoding": "Zeichenkodierung für Passwort (UTF-8 empfohlen)",
        "tooltip_windows_volume_path": "Windows Volume-GUID oder Gerätepfad",
        "tooltip_mount_letter": "Laufwerksbuchstabe zum Einbinden (A-Z)",
        "tooltip_veracrypt_path": "Pfad zur VeraCrypt.exe",
        "tooltip_unix_volume_path": "Unix-Gerätepfad (z. B. /dev/sdb2)",
        "tooltip_mount_point": "Unix-Einhängepunkt-Verzeichnis",
        "tooltip_recovery_enabled": "Notfall-Wiederherstellungs-Kit-Generierung aktivieren",
        "tooltip_recovery_share_count": "Anzahl der zu generierenden Wiederherstellungsanteile",
        "tooltip_recovery_threshold": "Mindestanzahl benötigter Anteile zur Wiederherstellung",
        "tooltip_lost_and_found_enabled": "Rückgabenachricht aktivieren, wenn Laufwerk verloren geht",
        "tooltip_lost_and_found_message": "Nachricht, die angezeigt wird, wenn Laufwerk gefunden wird",
        "tooltip_source_type": "Update-Quelle: lokales Verzeichnis oder Server-URL",
        "tooltip_server_url": "Server-URL für Updates",
        "tooltip_local_root": "Lokales Verzeichnis mit Update-Dateien",
        "tooltip_verification_overridden": "Integritätsprüfung umgehen (gefährlich!)",
        "tooltip_integrity_signed": "Laufwerksintegrität wurde kryptografisch signiert",
        "tooltip_signing_key_fpr": "GPG-Schlüssel-Fingerabdruck für Signatur",
        "tooltip_salt_b64": "Kryptografisches Salt für Schlüsselableitung",
        "tooltip_hkdf_info": "Kontextzeichenfolge für HKDF-Schlüsselableitung",
    },
    "bs": {
        # Window titles
        "window_title": "KeyDrive",
        "settings_window_title": "Postavke",
        
        # Button labels
        "btn_mount": "🔓 Montiraj",
        "btn_unmount": "🔒 Demontiraj",
        "btn_cancel_auth": "❌ Otkaži",
        "btn_confirm_mount": "✅ Potvrdi",
        "btn_tools": "⚙️",
        "btn_close": "✕",
        "btn_save": "Sačuvaj",
        "btn_cancel": "Otkaži",
        
        # Status messages
        "status_config_not_found": "Konfiguracija nije pronađena",
        "status_volume_mounted": "Volumen montiran",
        "status_volume_not_mounted": "Volumen nije montiran",
        "status_mounting": "⏳ Montiranje volumena...",
        "status_mounting_gpg": "⏳ Montiranje volumena (GPG autentifikacija)...",
        "status_unmounting": "⏳ Demontiranje volumena...",
        "status_mount_success": "✅ Volumen uspješno montiran",
        "status_mount_failed": "❌ Montiranje nije uspjelo",
        "status_unmount_success": "✅ Volumen uspješno demontiran",
        "status_unmount_failed": "❌ Demontiranje nije uspjelo",
        
        # Info labels
        "info_unavailable": "Informacije nisu dostupne",
        "keyfile_selected_one": "Odabrana 1 datoteka ključa",
        "keyfile_selected_many": "Odabrano {count} datoteka ključa",
        "keyfile_drop_hint": "Prevucite datoteke ključa ovdje ili kliknite za odabir",
        "keyfile_drop_supports_multiple": "Podržava više datoteka ključa",
        "label_show_password": "Prikaži lozinku",
        
        # Size formatting
        "size_free": "Slobodno: {size}",
        
        # Icons/placeholders
        "icon_drive": "🚀",
        
        # Tooltips
        "tooltip_exit": "Izađi iz SmartDrive",
        "tooltip_settings": "Napredni alati i postavke",
        
        # Labels
        "label_product_name": "Naziv proizvoda",
        "label_preview": "Pregled:",
        "label_password": "Lozinka:",
        "label_keyfile": "Datoteka ključa:",
        "label_hardware_key_hint": "💡 Hardverski ključ može biti potreban za autentifikaciju",
        "label_forgot_password": "Zaboravili ste lozinku?",
        
        # Placeholder text
        "placeholder_password": "Unesite svoju VeraCrypt lozinku...",
        
        # Menu items
        "menu_settings": "⚙️ Postavke",
        "menu_rekey": "🔑 Promijeni lozinku/datoteku ključa",
        "menu_update": "⬇️ Ažuriraj skripte",
        "menu_recovery": "💾 Paket za oporavak",
        "menu_about": "ℹ️ O programu",
        "menu_cli": "💻 Otvori CLI",
        "menu_clear_keyfiles": "Očisti datoteke ključa",
        "dialog_select_keyfiles": "Odaberite datoteku(e) ključa",
        
        # Tray messages
        "tray_minimized_message": "Radi u pozadini. Kliknite na ikonu u sistemskoj traci za vraćanje.",
        "tray_tooltip": "{name} ({id})",
        
        # Worker messages (keys for structured errors)
        "worker_mount_script_not_found": "Skripta za montiranje nije pronađena",
        "worker_mount_success": "Volumen uspješno montiran",
        "worker_mount_failed": "Montiranje nije uspjelo: {error}",
        "worker_mount_timeout": "Vrijeme za montiranje je isteklo",
        "worker_mount_error": "Greška pri montiranju: {error}",
        "worker_unmount_script_not_found": "Skripta za demontiranje nije pronađena",
        "worker_unmount_success": "Volumen uspješno demontiran",
        "worker_unmount_failed": "Demontiranje nije uspjelo: {error}",
        "worker_unmount_timeout": "Vrijeme za demontiranje je isteklo",
        "worker_unmount_error": "Greška pri demontiranju: {error}",
        
        # Settings dialog - Tab names
        "settings_language": "Jezik",
        "settings_general": "Opšte",
        "settings_security": "Sigurnost",
        "settings_keyfile": "Datoteka ključa",
        "settings_windows": "Windows",
        "settings_unix": "Unix",
        "settings_updates": "Ažuriranja",
        "settings_recovery": "Oporavak",
        "settings_lost_and_found": "Izgubljeno i nađeno",
        "settings_advanced": "Napredno",
        
        # Settings dialog - Tab descriptions
        "settings_general_desc": "Konfigurirajte ime prikaza, jezik i postavke teme.",
        "settings_security_desc": "Postavite način šifriranja i metodu autentifikacije za vaš sigurni disk.",
        "settings_keyfile_desc": "Upravljajte putanjama datoteka ključeva za šifriranje i GPG autentifikaciju.",
        "settings_windows_desc": "Windows-specifične postavke uključujući slovo diska i lokaciju VeraCrypt-a.",
        "settings_unix_desc": "Postavke za Linux i macOS uključujući direktorij točke montiranja.",
        "settings_updates_desc": "Konfigurirajte automatsku provjeru ažuriranja i postavke servera.",
        "settings_recovery_desc": "Postavite Shamir Secret Sharing opcije oporavka za pristup ako se ključevi izgube.",
        "settings_lost_and_found_desc": "Prikažite poruku za kontakt na disku za vraćanje ako se izgubi.",
        "settings_advanced_desc": "Tehničke postavke za parametre šifriranja i provjeru integriteta.",
        
        "settings_restart_not_required": "✓ Promjene su odmah primijenjene (restart nije potreban)",
        "label_mode": "Način",
        "label_encrypted_keyfile": "Šifrirana datoteka ključa",
        "label_volume_path": "Putanja do volumena",
        "label_mount_letter": "Slovo diska",
        "label_veracrypt_path": "Putanja do VeraCrypt-a",
        "label_mount_point": "Tačka montiranja",
        "label_source_type": "Tip izvora",
        "label_server_url": "URL servera",
        "label_local_root": "Lokalni korijenski direktorij",
        "error_invalid_mount_letter": "Slovo diska mora biti jedno slovo A–Z.",
        "error_save_failed": "Nije moguće sačuvati config.json:",
        "title_invalid_mount_letter": "Neispravno slovo diska",
        "title_save_failed": "Neuspjelo čuvanje",
        
        # Popup dialogs
        "popup_keyfile_required_title": "Potrebna datoteka ključa",
        "popup_keyfile_required_body": "Molimo odaberite datoteku ključa za režim lozinka + datoteka ključa.",
        "popup_password_required_title": "Potrebna lozinka",
        "popup_password_required_body": "Molimo unesite svoju VeraCrypt lozinku.",
        "popup_recovery_title": "Oporavak lozinke",
        "popup_recovery_available_body": "Paket za oporavak je dostupan za ovaj disk!\n\nZa povrat pristupa vašem šifriranom volumenu:\n\n1. Koristite SmartDrive CLI: python smartdrive.py\n2. Odaberite opciju 6: Paket za oporavak\n3. Pratite upute za oporavak\n\nIli kontaktirajte sistem administratora.",
        "popup_recovery_unavailable_body": "Trenutno nema dostupnog paketa za oporavak za ovaj disk.\n\nZa postavljanje oporavka lozinke:\n\n1. Koristite SmartDrive CLI: python smartdrive.py\n2. Odaberite opciju 6: Paket za oporavak\n3. Izaberite 'Generate Recovery Kit'\n\nIli kontaktirajte sistem administratora.",
        
        # Recovery tab - Phrase input and recovery actions
        "recovery_section_title": "🔐 Hitni oporavak",
        "recovery_instructions": "Unesite svoju frazu za oporavak od 24 riječi da biste povratili pristup vašem šifriranom volumenu. Možete također navesti datoteku kontejnera za oporavak ako je imate.",
        "label_recovery_phrase": "Fraza za oporavak (24 riječi):",
        "placeholder_recovery_phrase": "Unesite 24 riječi odvojene razmacima...",
        "label_recovery_container": "Kontejner za oporavak (opcionalno):",
        "btn_browse_container": "Pregledaj...",
        "btn_recover_credentials": "🔓 Povrati pristupne podatke",
        "recovery_status_ready": "Unesite svoju frazu za oporavak i kliknite 'Povrati pristupne podatke'",
        "recovery_status_validating": "Validacija fraze za oporavak...",
        "recovery_status_decrypting": "Dešifriranje kontejnera za oporavak...",
        "recovery_status_success": "✅ Oporavak uspješan! Pristupni podaci vraćeni.",
        "recovery_status_failed": "❌ Oporavak nije uspio: {error}",
        "recovery_result_title": "Vraćeni pristupni podaci",
        "recovery_result_password": "Lozinka:",
        "recovery_result_keyfile": "Datoteka ključa:",
        "recovery_result_mode": "Sigurnosni način:",
        "recovery_result_copy_password": "📋 Kopiraj lozinku",
        "recovery_result_save_keyfile": "💾 Sačuvaj datoteku ključa",
        "recovery_copied_to_clipboard": "Lozinka kopirana u međuspremnik (automatski se briše za 30 sekundi)",
        "recovery_keyfile_saved": "Datoteka ključa sačuvana u: {path}",
        "recovery_phrase_invalid": "Neispravna fraza za oporavak. Molimo provjerite svih 24 riječi.",
        "recovery_container_not_found": "Kontejner za oporavak nije pronađen. Molimo odaberite datoteku kontejnera.",
        "recovery_no_kit_configured": "Nijedan paket za oporavak nije konfigurisan za ovaj disk.",
        "recovery_generate_first": "Molimo prvo generirajte paket za oporavak putem Postavki ili CLI-ja.",
        
        "popup_unmount_failed_title": "Demontiranje nije uspjelo",
        "popup_mount_failed_title": "Montiranje nije uspjelo",
        "popup_update_not_possible_title": "Ažuriranje nije moguće",
        "popup_update_confirm_title": "Potvrdi ažuriranje",
        "popup_update_confirm_message": "Spremno za pokretanje UPDATE ({direction}).\n\nOD:\n  {src_root}\n\nDO:\n  {dst_root}\n\nStavke:\n  - {items}\n\nMetoda: {method}\n\nOvo će prepisati postojeće datoteke. Nastaviti?",
        "popup_update_config_title": "Konfiguracija ažuriranja",
        "popup_update_config_body": "Izvor ažuriranja nije konfigurisan. Postavite ga u Postavkama.",
        "popup_update_complete_title": "Ažuriranje završeno",
        "popup_update_complete_body": "Ažuriranje je uspješno završeno. Molimo ponovo pokrenite aplikaciju.",
        "popup_update_failed_title": "Ažuriranje nije uspjelo",
        "popup_update_failed_body": "Ažuriranje nije uspjelo:\n\n{error}",
        "popup_update_timeout_title": "Ažuriranje je isteklo",
        "popup_update_timeout_body": "Ažuriranje nije završeno u roku od 120 sekundi.",
        "popup_update_error_title": "Greška ažuriranja",
        "popup_update_error_body": "Neuspjelo pokretanje ažuriranja:\n\n{error}",
        "popup_cli_failed_title": "Pokretanje CLI-ja nije uspjelo",
        "popup_cli_failed_body": "Nije moguće otvoriti CLI:\n\n{error}",
        
        # Update configuration error messages
        "error_update_server_url_not_configured": "Server URL nije konfigurisan.\n\nIdite u Postavke da konfigurirate URL za ažuriranje.",
        "error_update_local_root_not_configured": "Lokalni direktorij za ažuriranje nije konfigurisan.\n\nIdite u Postavke da konfigurirate lokalni root za ažuriranje.",
        "error_update_local_root_not_found": "Lokalni direktorij za ažuriranje nije pronađen:\n\n{path}\n\nProvjerite Postavke da verifikujete putanju.",
        "error_update_install_dir_not_found": "Instalacijski direktorij nije pronađen:\n\n{path}",
        "error_update_unknown_source_type": "Nepoznat tip izvora ažuriranja: {type}",
        
        # Hardware key error messages
        "error_hardware_key_missing_title": "Potreban hardverski ključ",
        "error_hardware_key_missing_body": "Hardverski ključ (YubiKey/GPG kartica) nije detektovan. Molimo ubacite hardverski ključ i pokušajte ponovo.",
        
        # Theme names (for theme dropdown)
        "theme_green": "Zelena (zadano)",
        "theme_blue": "Plava",
        "theme_rose": "Ružičasta",
        "theme_slate": "Škriljac",
        "label_theme": "Tema",
        
        # File explorer buttons
        "tooltip_open_launcher_drive": "Otvori launcher disk",
        "tooltip_open_mounted_volume": "Otvori montirani volumen",
        "popup_open_failed_title": "Otvaranje nije uspjelo",
        "popup_open_failed_body": "Nije moguće otvoriti upravitelj datoteka:\n\n{path}\n\n{error}",
        
        # Settings dialog - Additional fields (schema-driven UI)
        "label_drive_id": "ID diska",
        "label_drive_name": "Naziv diska",
        "label_setup_date": "Datum postavljanja",
        "label_last_password_change": "Posljednja promjena lozinke",
        "label_last_verified": "Posljednja provjera",
        "label_plain_keyfile": "Obična datoteka ključa",
        "label_seed_gpg_path": "GPG seed datoteka",
        "label_kdf": "Funkcija izvođenja ključa",
        "label_pw_encoding": "Kodiranje lozinke",
        "label_recovery_enabled": "Omogući paket za oporavak",
        "label_recovery_share_count": "Broj dijelova za oporavak",
        "label_recovery_threshold": "Prag oporavka",
        "label_lost_and_found_enabled": "Omogući poruku pronađenog",
        "label_lost_and_found_message": "Poruka povrata",
        "label_verification_overridden": "Provjera zaobiđena",
        "label_integrity_signed": "Integritet potpisan",
        "label_signing_key_fpr": "Otisak prsta ključa potpisa",
        "label_salt_b64": "Salt (Base64)",
        "label_hkdf_info": "HKDF Info",
        "label_schema_version": "Verzija šeme",
        "label_version": "Verzija",
        
        # Tooltips for settings fields
        "tooltip_drive_id": "Jedinstveni identifikator za ovaj disk (samo za čitanje)",
        "tooltip_drive_name": "Prilagođeni naziv za ovaj disk",
        "tooltip_language": "Jezik korisničkog interfejsa",
        "tooltip_theme": "Šema boja za interfejs",
        "tooltip_mode": "Sigurnosni način: samo lozinka, datoteka ključa ili YubiKey/GPG",
        "tooltip_encrypted_keyfile": "Putanja do GPG-šifrirane datoteke ključa (za GPG načine)",
        "tooltip_plain_keyfile": "Putanja do nešifrirane datoteke ključa (za običan način datoteke ključa)",
        "tooltip_seed_gpg_path": "Putanja do GPG seed datoteke za izvođenje lozinke",
        "tooltip_kdf": "Funkcija izvođenja ključa za GPG način lozinke",
        "tooltip_pw_encoding": "Kodiranje znakova za lozinku (UTF-8 preporučeno)",
        "tooltip_windows_volume_path": "Windows volumen GUID ili putanja uređaja",
        "tooltip_mount_letter": "Slovo diska za montiranje (A-Z)",
        "tooltip_veracrypt_path": "Putanja do VeraCrypt.exe izvršne datoteke",
        "tooltip_unix_volume_path": "Unix putanja uređaja (npr. /dev/sdb2)",
        "tooltip_mount_point": "Unix direktorij tačke montiranja",
        "tooltip_recovery_enabled": "Omogući generisanje hitnog paketa za oporavak",
        "tooltip_recovery_share_count": "Broj dijelova za oporavak za generisanje",
        "tooltip_recovery_threshold": "Minimalan broj dijelova potrebnih za oporavak",
        "tooltip_lost_and_found_enabled": "Omogući poruku povrata ako je disk izgubljen",
        "tooltip_lost_and_found_message": "Poruka prikazana ako je disk pronađen",
        "tooltip_source_type": "Izvor ažuriranja: lokalni direktorij ili URL servera",
        "tooltip_server_url": "URL servera za ažuriranja",
        "tooltip_local_root": "Lokalni direktorij sa datotekama ažuriranja",
        "tooltip_verification_overridden": "Zaobiđi provjeru integriteta (opasno!)",
        "tooltip_integrity_signed": "Integritet diska je kriptografski potpisan",
        "tooltip_signing_key_fpr": "Otisak prsta GPG ključa korišten za potpis",
        "tooltip_salt_b64": "Kriptografski salt za izvođenje ključa",
        "tooltip_hkdf_info": "Kontekstni string za HKDF izvođenje ključa",
    },
    "es": {
        # Window titles
        "window_title": "KeyDrive",
        "settings_window_title": "Configuración",
        
        # Button labels
        "btn_mount": "🔓 Montar",
        "btn_unmount": "🔒 Desmontar",
        "btn_cancel_auth": "❌ Cancelar",
        "btn_confirm_mount": "✅ Confirmar",
        "btn_tools": "⚙️",
        "btn_close": "✕",
        "btn_save": "Guardar",
        "btn_cancel": "Cancelar",
        
        # Status messages
        "status_config_not_found": "Configuración no encontrada",
        "status_volume_mounted": "Volumen montado",
        "status_volume_not_mounted": "Volumen no montado",
        "status_mounting": "⏳ Montando volumen...",
        "status_mounting_gpg": "⏳ Montando volumen (autenticación GPG)...",
        "status_unmounting": "⏳ Desmontando volumen...",
        "status_mount_success": "✅ Volumen montado correctamente",
        "status_mount_failed": "❌ Error al montar",
        "status_unmount_success": "✅ Volumen desmontado correctamente",
        "status_unmount_failed": "❌ Error al desmontar",
        
        # Info labels
        "info_unavailable": "Información no disponible",
        "keyfile_selected_one": "1 archivo de clave seleccionado",
        "keyfile_selected_many": "{count} archivos de clave seleccionados",
        "keyfile_drop_hint": "Arrastra los archivos de clave aquí o haz clic para buscar",
        "keyfile_drop_supports_multiple": "Admite varios archivos de clave",
        "label_show_password": "Mostrar contraseña",
        
        # Size formatting
        "size_free": "Libre: {size}",
        
        # Icons/placeholders
        "icon_drive": "🚀",
        
        # Tooltips
        "tooltip_exit": "Salir de SmartDrive",
        "tooltip_settings": "Herramientas y configuración avanzadas",
        
        # Labels
        "label_product_name": "Nombre del producto",
        "label_preview": "Vista previa:",
        "label_password": "Contraseña:",
        "label_keyfile": "Archivo de clave:",
        "label_hardware_key_hint": "💡 Puede requerirse una llave de hardware para la autenticación",
        "label_forgot_password": "¿Olvidaste tu contraseña?",
        
        # Placeholder text
        "placeholder_password": "Introduce tu contraseña de VeraCrypt...",
        
        # Menu items
        "menu_settings": "⚙️ Configuración",
        "menu_rekey": "🔑 Cambiar contraseña/archivo de clave",
        "menu_update": "⬇️ Actualizar scripts",
        "menu_recovery": "💾 Kit de recuperación",
        "menu_about": "ℹ️ Acerca de",
        "menu_cli": "💻 Abrir CLI",
        "menu_clear_keyfiles": "Borrar archivos de clave",
        "dialog_select_keyfiles": "Seleccionar archivo(s) de clave",
        
        # Tray
        "tray_minimized_message": "Ejecutándose en segundo plano. Haz clic en el icono de la bandeja para abrir.",
        "tray_tooltip": "{name} ({id})",
        
        # Worker messages (keys for structured errors)
        "worker_mount_script_not_found": "No se encontró el script de montaje",
        "worker_mount_success": "Volumen montado correctamente",
        "worker_mount_failed": "Error al montar: {error}",
        "worker_mount_timeout": "Tiempo de espera agotado al montar",
        "worker_mount_error": "Error de montaje: {error}",
        "worker_unmount_script_not_found": "No se encontró el script de desmontaje",
        "worker_unmount_success": "Volumen desmontado correctamente",
        "worker_unmount_failed": "Error al desmontar: {error}",
        "worker_unmount_timeout": "Tiempo de espera agotado al desmontar",
        "worker_unmount_error": "Error de desmontaje: {error}",
        
        # Settings dialog - Tab names
        "settings_language": "Idioma",
        "settings_general": "General",
        "settings_security": "Seguridad",
        "settings_keyfile": "Archivo de clave",
        "settings_windows": "Windows",
        "settings_unix": "Unix",
        "settings_updates": "Actualizaciones",
        "settings_recovery": "Recuperación",
        "settings_lost_and_found": "Perdido y encontrado",
        "settings_advanced": "Avanzado",
        
        # Settings dialog - Tab descriptions
        "settings_general_desc": "Configure el nombre para mostrar, el idioma y las preferencias de tema.",
        "settings_security_desc": "Establezca el modo de cifrado y el método de autenticación para su unidad segura.",
        "settings_keyfile_desc": "Administre las rutas de archivos de clave para cifrado y autenticación GPG.",
        "settings_windows_desc": "Configuración específica de Windows incluyendo letra de unidad y ubicación de VeraCrypt.",
        "settings_unix_desc": "Configuración de Linux y macOS incluyendo directorio del punto de montaje.",
        "settings_updates_desc": "Configure la verificación automática de actualizaciones y la configuración del servidor.",
        "settings_recovery_desc": "Configure las opciones de recuperación Shamir Secret Sharing para recuperar el acceso si se pierden las claves.",
        "settings_lost_and_found_desc": "Muestre un mensaje de contacto en la unidad para su devolución si se pierde.",
        "settings_advanced_desc": "Configuración técnica para parámetros de cifrado y verificación de integridad.",
        
        "settings_restart_not_required": "✓ Cambios aplicados inmediatamente (no se requiere reinicio)",
        "label_mode": "Modo",
        "label_encrypted_keyfile": "Archivo de clave cifrado",
        "label_volume_path": "Ruta del volumen",
        "label_mount_letter": "Letra de unidad",
        "label_veracrypt_path": "Ruta de VeraCrypt",
        "label_mount_point": "Punto de montaje",
        "label_source_type": "Tipo de origen",
        "label_server_url": "URL del servidor",
        "label_local_root": "Raíz local",
        "error_invalid_mount_letter": "La letra de unidad debe ser un solo carácter A–Z.",
        "error_save_failed": "No se pudo guardar config.json:",
        "title_invalid_mount_letter": "Letra de unidad no válida",
        "title_save_failed": "Error al guardar",
        
        # Popup dialogs
        "popup_keyfile_required_title": "Se requiere archivo de clave",
        "popup_keyfile_required_body": "Selecciona un archivo de clave para el modo contraseña + archivo de clave.",
        "popup_password_required_title": "Se requiere contraseña",
        "popup_password_required_body": "Introduce tu contraseña de VeraCrypt.",
        "popup_recovery_title": "Recuperación de contraseña",
        "popup_recovery_available_body": "¡Hay un kit de recuperación disponible para esta unidad!\n\nPara recuperar el acceso a tu volumen cifrado:\n\n1. Usa la CLI de SmartDrive: python smartdrive.py\n2. Selecciona la opción 6: Kit de recuperación\n3. Sigue las instrucciones de recuperación\n\nO contacta con tu administrador del sistema.",
        "popup_recovery_unavailable_body": "Actualmente no hay un kit de recuperación disponible para esta unidad.\n\nPara configurar la recuperación de contraseña:\n\n1. Usa la CLI de SmartDrive: python smartdrive.py\n2. Selecciona la opción 6: Kit de recuperación\n3. Elige 'Generate Recovery Kit'\n\nO contacta con tu administrador del sistema.",
        
        # Recovery tab - Phrase input and recovery actions
        "recovery_section_title": "🔐 Recuperación de emergencia",
        "recovery_instructions": "Introduce tu frase de recuperación de 24 palabras para recuperar el acceso a tu volumen cifrado. También puedes proporcionar un archivo contenedor de recuperación si tienes uno.",
        "label_recovery_phrase": "Frase de recuperación (24 palabras):",
        "placeholder_recovery_phrase": "Introduce 24 palabras separadas por espacios...",
        "label_recovery_container": "Contenedor de recuperación (opcional):",
        "btn_browse_container": "Examinar...",
        "btn_recover_credentials": "🔓 Recuperar credenciales",
        "recovery_status_ready": "Introduce tu frase de recuperación y haz clic en 'Recuperar credenciales'",
        "recovery_status_validating": "Validando frase de recuperación...",
        "recovery_status_decrypting": "Descifrando contenedor de recuperación...",
        "recovery_status_success": "✅ ¡Recuperación exitosa! Credenciales recuperadas.",
        "recovery_status_failed": "❌ Error en la recuperación: {error}",
        "recovery_result_title": "Credenciales recuperadas",
        "recovery_result_password": "Contraseña:",
        "recovery_result_keyfile": "Archivo de clave:",
        "recovery_result_mode": "Modo de seguridad:",
        "recovery_result_copy_password": "📋 Copiar contraseña",
        "recovery_result_save_keyfile": "💾 Guardar archivo de clave",
        "recovery_copied_to_clipboard": "Contraseña copiada al portapapeles (se borrará en 30 segundos)",
        "recovery_keyfile_saved": "Archivo de clave guardado en: {path}",
        "recovery_phrase_invalid": "Frase de recuperación no válida. Verifica las 24 palabras.",
        "recovery_container_not_found": "Contenedor de recuperación no encontrado. Selecciona el archivo contenedor.",
        "recovery_no_kit_configured": "No hay kit de recuperación configurado para esta unidad.",
        "recovery_generate_first": "Por favor genera primero un kit de recuperación desde Configuración o CLI.",
        
        "popup_unmount_failed_title": "Error al desmontar",
        "popup_mount_failed_title": "Error al montar",
        "popup_update_not_possible_title": "Actualización no posible",
        "popup_update_confirm_title": "Confirmar actualización",
        "popup_update_confirm_message": "Se va a ejecutar UPDATE ({direction}).\n\nDESDE:\n  {src_root}\n\nHACIA:\n  {dst_root}\n\nElementos:\n  - {items}\n\nMétodo: {method}\n\nEsto sobrescribirá los archivos existentes. ¿Continuar?",
        "popup_update_config_title": "Configuración de actualización",
        "popup_update_config_body": "La fuente de actualización no está configurada. Configúrala en Configuración.",
        "popup_update_complete_title": "Actualización completa",
        "popup_update_complete_body": "La actualización finalizó correctamente. Reinicia la aplicación.",
        "popup_update_failed_title": "Actualización fallida",
        "popup_update_failed_body": "La actualización falló:\n\n{error}",
        "popup_update_timeout_title": "Tiempo de espera de actualización",
        "popup_update_timeout_body": "La actualización no se completó en 120 segundos.",
        "popup_update_error_title": "Error de actualización",
        "popup_update_error_body": "No se pudo ejecutar la actualización:\n\n{error}",
        "popup_cli_failed_title": "Error al iniciar CLI",
        "popup_cli_failed_body": "No se pudo abrir la CLI:\n\n{error}",
        
        # Update configuration error messages
        "error_update_server_url_not_configured": "El URL del servidor no está configurado.\n\nVe a Configuración para configurar el URL de actualización.",
        "error_update_local_root_not_configured": "El directorio de actualización local no está configurado.\n\nVe a Configuración para configurar la raíz local de actualización.",
        "error_update_local_root_not_found": "No se encontró el directorio de actualización local:\n\n{path}\n\nComprueba Configuración para verificar la ruta.",
        "error_update_install_dir_not_found": "No se encontró el directorio de instalación:\n\n{path}",
        "error_update_unknown_source_type": "Tipo de origen de actualización desconocido: {type}",
        
        # Hardware key error messages
        "error_hardware_key_missing_title": "Se requiere llave de hardware",
        "error_hardware_key_missing_body": "No se detectó la llave de hardware (YubiKey/tarjeta GPG). Inserta tu llave de hardware e inténtalo de nuevo.",
        
        # Theme names (for theme dropdown)
        "theme_green": "Verde (predeterminado)",
        "theme_blue": "Azul",
        "theme_rose": "Rosa",
        "theme_slate": "Pizarra",
        "label_theme": "Tema",
        
        # File explorer buttons
        "tooltip_open_launcher_drive": "Abrir unidad del launcher",
        "tooltip_open_mounted_volume": "Abrir volumen montado",
        "popup_open_failed_title": "Error al abrir",
        "popup_open_failed_body": "No se pudo abrir el explorador de archivos:\n\n{path}\n\n{error}",
        
        # Settings dialog - Additional fields (schema-driven UI)
        "label_drive_id": "ID de unidad",
        "label_drive_name": "Nombre de unidad",
        "label_setup_date": "Fecha de configuración",
        "label_last_password_change": "Último cambio de contraseña",
        "label_last_verified": "Última verificación",
        "label_plain_keyfile": "Archivo de clave simple",
        "label_seed_gpg_path": "Archivo semilla GPG",
        "label_kdf": "Función de derivación de clave",
        "label_pw_encoding": "Codificación de contraseña",
        "label_recovery_enabled": "Habilitar kit de recuperación",
        "label_recovery_share_count": "Número de partes de recuperación",
        "label_recovery_threshold": "Umbral de recuperación",
        "label_lost_and_found_enabled": "Habilitar mensaje de objetos perdidos",
        "label_lost_and_found_message": "Mensaje de devolución",
        "label_verification_overridden": "Verificación anulada",
        "label_integrity_signed": "Integridad firmada",
        "label_signing_key_fpr": "Huella digital de clave de firma",
        "label_salt_b64": "Salt (Base64)",
        "label_hkdf_info": "Info HKDF",
        "label_schema_version": "Versión del esquema",
        "label_version": "Versión",
        
        # Tooltips for settings fields
        "tooltip_drive_id": "Identificador único para esta unidad (solo lectura)",
        "tooltip_drive_name": "Nombre personalizado para esta unidad",
        "tooltip_language": "Idioma de la interfaz de usuario",
        "tooltip_theme": "Esquema de color para la interfaz",
        "tooltip_mode": "Modo de seguridad: solo contraseña, archivo de clave o YubiKey/GPG",
        "tooltip_encrypted_keyfile": "Ruta al archivo de clave cifrado con GPG (para modos GPG)",
        "tooltip_plain_keyfile": "Ruta al archivo de clave no cifrado (para modo de archivo de clave simple)",
        "tooltip_seed_gpg_path": "Ruta al archivo semilla GPG para derivación de contraseña",
        "tooltip_kdf": "Función de derivación de clave para modo de contraseña GPG",
        "tooltip_pw_encoding": "Codificación de caracteres para contraseña (se recomienda UTF-8)",
        "tooltip_windows_volume_path": "GUID de volumen de Windows o ruta de dispositivo",
        "tooltip_mount_letter": "Letra de unidad para montar como (A-Z)",
        "tooltip_veracrypt_path": "Ruta al ejecutable VeraCrypt.exe",
        "tooltip_unix_volume_path": "Ruta de dispositivo Unix (p. ej., /dev/sdb2)",
        "tooltip_mount_point": "Directorio de punto de montaje Unix",
        "tooltip_recovery_enabled": "Habilitar generación de kit de recuperación de emergencia",
        "tooltip_recovery_share_count": "Número de partes de recuperación para generar",
        "tooltip_recovery_threshold": "Número mínimo de partes necesarias para recuperación",
        "tooltip_lost_and_found_enabled": "Habilitar mensaje de devolución si se pierde la unidad",
        "tooltip_lost_and_found_message": "Mensaje mostrado si se encuentra la unidad",
        "tooltip_source_type": "Fuente de actualización: directorio local o URL del servidor",
        "tooltip_server_url": "URL del servidor para actualizaciones",
        "tooltip_local_root": "Directorio local que contiene archivos de actualización",
        "tooltip_verification_overridden": "Omitir verificación de integridad (¡peligroso!)",
        "tooltip_integrity_signed": "La integridad de la unidad ha sido firmada criptográficamente",
        "tooltip_signing_key_fpr": "Huella digital de clave GPG usada para firmar",
        "tooltip_salt_b64": "Salt criptográfico para derivación de clave",
        "tooltip_hkdf_info": "Cadena de contexto para derivación de clave HKDF",
    },
    "fr": {
        # Window titles
        "window_title": "KeyDrive",
        "settings_window_title": "Paramètres",
        
        # Button labels
        "btn_mount": "🔓 Monter",
        "btn_unmount": "🔒 Démonter",
        "btn_cancel_auth": "❌ Annuler",
        "btn_confirm_mount": "✅ Confirmer",
        "btn_tools": "⚙️",
        "btn_close": "✕",
        "btn_save": "Enregistrer",
        "btn_cancel": "Annuler",
        
        # Status messages
        "status_config_not_found": "Configuration introuvable",
        "status_volume_mounted": "Volume monté",
        "status_volume_not_mounted": "Volume non monté",
        "status_mounting": "⏳ Montage du volume...",
        "status_mounting_gpg": "⏳ Montage du volume (authentification GPG)...",
        "status_unmounting": "⏳ Démontage du volume...",
        "status_mount_success": "✅ Volume monté avec succès",
        "status_mount_failed": "❌ Échec du montage",
        "status_unmount_success": "✅ Volume démonté avec succès",
        "status_unmount_failed": "❌ Échec du démontage",
        
        # Info labels
        "info_unavailable": "Infos indisponibles",
        "keyfile_selected_one": "1 fichier clé sélectionné",
        "keyfile_selected_many": "{count} fichiers clés sélectionnés",
        "keyfile_drop_hint": "Déposez les fichiers clés ici ou cliquez pour parcourir",
        "keyfile_drop_supports_multiple": "Prend en charge plusieurs fichiers clés",
        "label_show_password": "Afficher le mot de passe",
        
        # Size formatting
        "size_free": "Libre : {size}",
        
        # Icons/placeholders
        "icon_drive": "🚀",
        
        # Tooltips
        "tooltip_exit": "Quitter SmartDrive",
        "tooltip_settings": "Outils et paramètres avancés",
        
        # Labels
        "label_product_name": "Nom du produit",
        "label_preview": "Aperçu :",
        "label_password": "Mot de passe :",
        "label_keyfile": "Fichier clé :",
        "label_hardware_key_hint": "💡 Une clé matérielle peut être requise pour l'authentification",
        "label_forgot_password": "Mot de passe oublié ?",
        
        # Placeholder text
        "placeholder_password": "Saisissez votre mot de passe VeraCrypt...",
        
        # Menu items
        "menu_settings": "⚙️ Paramètres",
        "menu_rekey": "🔑 Changer mot de passe/fichier clé",
        "menu_update": "⬇️ Mettre à jour les scripts",
        "menu_recovery": "💾 Kit de récupération",
        "menu_about": "ℹ️ À propos",
        "menu_cli": "💻 Ouvrir la CLI",
        "menu_clear_keyfiles": "Effacer les fichiers clés",
        "dialog_select_keyfiles": "Sélectionner le(s) fichier(s) clé(s)",
        
        # Tray
        "tray_minimized_message": "Exécution en arrière-plan. Cliquez sur l'icône de la barre pour ouvrir.",
        "tray_tooltip": "{name} ({id})",
        
        # Worker messages (keys for structured errors)
        "worker_mount_script_not_found": "Script de montage introuvable",
        "worker_mount_success": "Volume monté avec succès",
        "worker_mount_failed": "Échec du montage : {error}",
        "worker_mount_timeout": "Délai de montage dépassé",
        "worker_mount_error": "Erreur de montage : {error}",
        "worker_unmount_script_not_found": "Script de démontage introuvable",
        "worker_unmount_success": "Volume démonté avec succès",
        "worker_unmount_failed": "Échec du démontage : {error}",
        "worker_unmount_timeout": "Délai de démontage dépassé",
        "worker_unmount_error": "Erreur de démontage : {error}",
        
        # Settings dialog - Tab names
        "settings_language": "Langue",
        "settings_general": "Général",
        "settings_security": "Sécurité",
        "settings_keyfile": "Fichier clé",
        "settings_windows": "Windows",
        "settings_unix": "Unix",
        "settings_updates": "Mises à jour",
        "settings_recovery": "Récupération",
        "settings_lost_and_found": "Objets trouvés",
        "settings_advanced": "Avancé",
        
        # Settings dialog - Tab descriptions
        "settings_general_desc": "Configurez le nom d'affichage, la langue et les préférences de thème.",
        "settings_security_desc": "Définissez le mode de chiffrement et la méthode d'authentification pour votre disque sécurisé.",
        "settings_keyfile_desc": "Gérez les chemins des fichiers clés pour le chiffrement et l'authentification GPG.",
        "settings_windows_desc": "Paramètres spécifiques à Windows, notamment la lettre du lecteur et l'emplacement de VeraCrypt.",
        "settings_unix_desc": "Paramètres Linux et macOS, notamment le répertoire du point de montage.",
        "settings_updates_desc": "Configurez la vérification automatique des mises à jour et les paramètres du serveur.",
        "settings_recovery_desc": "Configurez les options de récupération Shamir Secret Sharing pour récupérer l'accès si les clés sont perdues.",
        "settings_lost_and_found_desc": "Affichez un message de contact sur le disque pour le récupérer s'il est perdu.",
        "settings_advanced_desc": "Paramètres techniques pour les paramètres de chiffrement et la vérification de l'intégrité.",
        
        "settings_restart_not_required": "✓ Modifications appliquées immédiatement (aucun redémarrage requis)",
        "label_mode": "Mode",
        "label_encrypted_keyfile": "Fichier clé chiffré",
        "label_volume_path": "Chemin du volume",
        "label_mount_letter": "Lettre de montage",
        "label_veracrypt_path": "Chemin de VeraCrypt",
        "label_mount_point": "Point de montage",
        "label_source_type": "Type de source",
        "label_server_url": "URL du serveur",
        "label_local_root": "Racine locale",
        "error_invalid_mount_letter": "La lettre de montage doit être un seul caractère A–Z.",
        "error_save_failed": "Impossible d'enregistrer config.json :",
        "title_invalid_mount_letter": "Lettre de montage non valide",
        "title_save_failed": "Échec de l'enregistrement",
        
        # Popup dialogs
        "popup_keyfile_required_title": "Fichier clé requis",
        "popup_keyfile_required_body": "Veuillez sélectionner un fichier clé pour le mode mot de passe + fichier clé.",
        "popup_password_required_title": "Mot de passe requis",
        "popup_password_required_body": "Veuillez saisir votre mot de passe VeraCrypt.",
        "popup_recovery_title": "Récupération de mot de passe",
        "popup_recovery_available_body": "Un kit de récupération est disponible pour ce lecteur !\n\nPour récupérer l'accès à votre volume chiffré :\n\n1. Utilisez la CLI SmartDrive : python smartdrive.py\n2. Sélectionnez l'option 6 : Kit de récupération\n3. Suivez les instructions de récupération\n\nOu contactez votre administrateur système.",
        "popup_recovery_unavailable_body": "Aucun kit de récupération n'est actuellement disponible pour ce lecteur.\n\nPour configurer la récupération de mot de passe :\n\n1. Utilisez la CLI SmartDrive : python smartdrive.py\n2. Sélectionnez l'option 6 : Kit de récupération\n3. Choisissez 'Generate Recovery Kit'\n\nOu contactez votre administrateur système.",
        
        # Recovery tab - Phrase input and recovery actions
        "recovery_section_title": "🔐 Récupération d'urgence",
        "recovery_instructions": "Entrez votre phrase de récupération de 24 mots pour récupérer l'accès à votre volume chiffré. Vous pouvez également fournir un fichier conteneur de récupération si vous en avez un.",
        "label_recovery_phrase": "Phrase de récupération (24 mots) :",
        "placeholder_recovery_phrase": "Entrez 24 mots séparés par des espaces...",
        "label_recovery_container": "Conteneur de récupération (optionnel) :",
        "btn_browse_container": "Parcourir...",
        "btn_recover_credentials": "🔓 Récupérer les identifiants",
        "recovery_status_ready": "Entrez votre phrase de récupération et cliquez sur 'Récupérer les identifiants'",
        "recovery_status_validating": "Validation de la phrase de récupération...",
        "recovery_status_decrypting": "Déchiffrement du conteneur de récupération...",
        "recovery_status_success": "✅ Récupération réussie ! Identifiants récupérés.",
        "recovery_status_failed": "❌ Échec de la récupération : {error}",
        "recovery_result_title": "Identifiants récupérés",
        "recovery_result_password": "Mot de passe :",
        "recovery_result_keyfile": "Fichier clé :",
        "recovery_result_mode": "Mode de sécurité :",
        "recovery_result_copy_password": "📋 Copier le mot de passe",
        "recovery_result_save_keyfile": "💾 Enregistrer le fichier clé",
        "recovery_copied_to_clipboard": "Mot de passe copié dans le presse-papiers (effacement auto dans 30 secondes)",
        "recovery_keyfile_saved": "Fichier clé enregistré dans : {path}",
        "recovery_phrase_invalid": "Phrase de récupération invalide. Veuillez vérifier les 24 mots.",
        "recovery_container_not_found": "Conteneur de récupération introuvable. Veuillez sélectionner le fichier conteneur.",
        "recovery_no_kit_configured": "Aucun kit de récupération configuré pour ce lecteur.",
        "recovery_generate_first": "Veuillez d'abord générer un kit de récupération via Paramètres ou CLI.",
        
        "popup_unmount_failed_title": "Échec du démontage",
        "popup_mount_failed_title": "Échec du montage",
        "popup_update_not_possible_title": "Mise à jour impossible",
        "popup_update_confirm_title": "Confirmer la mise à jour",
        "popup_update_confirm_message": "Sur le point d'exécuter UPDATE ({direction}).\n\nDE :\n  {src_root}\n\nVERS :\n  {dst_root}\n\nÉléments :\n  - {items}\n\nMéthode : {method}\n\nCela écrasera les fichiers existants. Continuer ?",
        "popup_update_config_title": "Configuration de mise à jour",
        "popup_update_config_body": "La source de mise à jour n'est pas configurée. Veuillez la définir dans Paramètres.",
        "popup_update_complete_title": "Mise à jour terminée",
        "popup_update_complete_body": "La mise à jour s'est terminée avec succès. Veuillez redémarrer l'application.",
        "popup_update_failed_title": "Échec de la mise à jour",
        "popup_update_failed_body": "Échec de la mise à jour :\n\n{error}",
        "popup_update_timeout_title": "Délai de mise à jour dépassé",
        "popup_update_timeout_body": "La mise à jour ne s'est pas terminée dans les 120 secondes.",
        "popup_update_error_title": "Erreur de mise à jour",
        "popup_update_error_body": "Impossible d'exécuter la mise à jour :\n\n{error}",
        "popup_cli_failed_title": "Échec du lancement de la CLI",
        "popup_cli_failed_body": "Impossible d'ouvrir la CLI :\n\n{error}",
        
        # Update configuration error messages
        "error_update_server_url_not_configured": "L'URL du serveur n'est pas configurée.\n\nAllez dans Paramètres pour configurer l'URL de mise à jour.",
        "error_update_local_root_not_configured": "Le répertoire de mise à jour local n'est pas configuré.\n\nAllez dans Paramètres pour configurer la racine locale de mise à jour.",
        "error_update_local_root_not_found": "Répertoire de mise à jour local introuvable :\n\n{path}\n\nVérifiez Paramètres pour valider le chemin.",
        "error_update_install_dir_not_found": "Répertoire d'installation introuvable :\n\n{path}",
        "error_update_unknown_source_type": "Type de source de mise à jour inconnu : {type}",
        
        # Hardware key error messages
        "error_hardware_key_missing_title": "Clé matérielle requise",
        "error_hardware_key_missing_body": "Clé matérielle (YubiKey/carte GPG) non détectée. Veuillez insérer votre clé matérielle et réessayer.",
        
        # Theme names (for theme dropdown)
        "theme_green": "Vert (par défaut)",
        "theme_blue": "Bleu",
        "theme_rose": "Rose",
        "theme_slate": "Ardoise",
        "label_theme": "Thème",
        
        # File explorer buttons
        "tooltip_open_launcher_drive": "Ouvrir le lecteur de lancement",
        "tooltip_open_mounted_volume": "Ouvrir le volume monté",
        "popup_open_failed_title": "Échec de l'ouverture",
        "popup_open_failed_body": "Impossible d'ouvrir l'explorateur de fichiers :\n\n{path}\n\n{error}",
        
        # Settings dialog - Additional fields (schema-driven UI)
        "label_drive_id": "ID du disque",
        "label_drive_name": "Nom du disque",
        "label_setup_date": "Date de configuration",
        "label_last_password_change": "Dernier changement de mot de passe",
        "label_last_verified": "Dernière vérification",
        "label_plain_keyfile": "Fichier clé simple",
        "label_seed_gpg_path": "Fichier semence GPG",
        "label_kdf": "Fonction de dérivation de clé",
        "label_pw_encoding": "Encodage du mot de passe",
        "label_recovery_enabled": "Activer le kit de récupération",
        "label_recovery_share_count": "Nombre de parts de récupération",
        "label_recovery_threshold": "Seuil de récupération",
        "label_lost_and_found_enabled": "Activer le message des objets trouvés",
        "label_lost_and_found_message": "Message de retour",
        "label_verification_overridden": "Vérification contournée",
        "label_integrity_signed": "Intégrité signée",
        "label_signing_key_fpr": "Empreinte de clé de signature",
        "label_salt_b64": "Sel (Base64)",
        "label_hkdf_info": "Info HKDF",
        "label_schema_version": "Version du schéma",
        "label_version": "Version",
        
        # Tooltips for settings fields
        "tooltip_drive_id": "Identifiant unique pour ce disque (lecture seule)",
        "tooltip_drive_name": "Nom personnalisé pour ce disque",
        "tooltip_language": "Langue de l'interface utilisateur",
        "tooltip_theme": "Schéma de couleur pour l'interface",
        "tooltip_mode": "Mode de sécurité : mot de passe uniquement, fichier clé ou YubiKey/GPG",
        "tooltip_encrypted_keyfile": "Chemin vers le fichier clé chiffré GPG (pour les modes GPG)",
        "tooltip_plain_keyfile": "Chemin vers le fichier clé non chiffré (pour le mode fichier clé simple)",
        "tooltip_seed_gpg_path": "Chemin vers le fichier semence GPG pour la dérivation du mot de passe",
        "tooltip_kdf": "Fonction de dérivation de clé pour le mode mot de passe GPG",
        "tooltip_pw_encoding": "Encodage des caractères pour le mot de passe (UTF-8 recommandé)",
        "tooltip_windows_volume_path": "GUID de volume Windows ou chemin du périphérique",
        "tooltip_mount_letter": "Lettre de lecteur pour monter comme (A-Z)",
        "tooltip_veracrypt_path": "Chemin vers l'exécutable VeraCrypt.exe",
        "tooltip_unix_volume_path": "Chemin du périphérique Unix (par ex. /dev/sdb2)",
        "tooltip_mount_point": "Répertoire de point de montage Unix",
        "tooltip_recovery_enabled": "Activer la génération de kit de récupération d'urgence",
        "tooltip_recovery_share_count": "Nombre de parts de récupération à générer",
        "tooltip_recovery_threshold": "Nombre minimum de parts nécessaires pour la récupération",
        "tooltip_lost_and_found_enabled": "Activer le message de retour si le disque est perdu",
        "tooltip_lost_and_found_message": "Message affiché si le disque est trouvé",
        "tooltip_source_type": "Source de mise à jour : répertoire local ou URL du serveur",
        "tooltip_server_url": "URL du serveur pour les mises à jour",
        "tooltip_local_root": "Répertoire local contenant les fichiers de mise à jour",
        "tooltip_verification_overridden": "Contourner la vérification d'intégrité (dangereux !)",
        "tooltip_integrity_signed": "L'intégrité du disque a été signée cryptographiquement",
        "tooltip_signing_key_fpr": "Empreinte de clé GPG utilisée pour la signature",
        "tooltip_salt_b64": "Sel cryptographique pour la dérivation de clé",
        "tooltip_hkdf_info": "Chaîne de contexte pour la dérivation de clé HKDF",
    },
    "ru": {
        # Window titles
        "window_title": "KeyDrive",
        "settings_window_title": "Настройки",

        # Button labels
        "btn_mount": "🔓 Смонтировать",
        "btn_unmount": "🔒 Размонтировать",
        "btn_cancel_auth": "❌ Отмена",
        "btn_confirm_mount": "✅ Подтвердить",
        "btn_tools": "⚙️",
        "btn_close": "✕",
        "btn_save": "Сохранить",
        "btn_cancel": "Отмена",

        # Status messages
        "status_config_not_found": "Конфигурация не найдена",
        "status_volume_mounted": "Том смонтирован",
        "status_volume_not_mounted": "Том не смонтирован",
        "status_mounting": "⏳ Монтирование тома...",
        "status_mounting_gpg": "⏳ Монтирование тома (GPG-аутентификация)...",
        "status_unmounting": "⏳ Размонтирование тома...",
        "status_mount_success": "✅ Том успешно смонтирован",
        "status_mount_failed": "❌ Ошибка монтирования",
        "status_unmount_success": "✅ Том успешно размонтирован",
        "status_unmount_failed": "❌ Ошибка размонтирования",

        # Info labels
        "info_unavailable": "Информация недоступна",
        "keyfile_selected_one": "Выбран 1 ключевой файл",
        "keyfile_selected_many": "Выбрано {count} ключевых файлов",
        "keyfile_drop_hint": "Перетащите ключевые файлы сюда или нажмите для выбора",
        "keyfile_drop_supports_multiple": "Поддерживает несколько ключевых файлов",
        "label_show_password": "Показать пароль",

        # Size formatting
        "size_free": "Свободно: {size}",

        # Icons/placeholders
        "icon_drive": "🚀",

        # Tooltips
        "tooltip_exit": "Выйти из SmartDrive",
        "tooltip_settings": "Дополнительные инструменты и настройки",

        # Labels
        "label_product_name": "Название продукта",
        "label_preview": "Предпросмотр:",
        "label_password": "Пароль:",
        "label_keyfile": "Ключевой файл:",
        "label_hardware_key_hint": "💡 Для аутентификации может потребоваться аппаратный ключ",
        "label_forgot_password": "Забыли пароль?",

        # Placeholder text
        "placeholder_password": "Введите пароль VeraCrypt...",

        # Menu items
        "menu_settings": "⚙️ Настройки",
        "menu_rekey": "🔑 Сменить пароль/ключевой файл",
        "menu_update": "⬇️ Обновить скрипты",
        "menu_recovery": "💾 Набор восстановления",
        "menu_about": "ℹ️ О программе",
        "menu_cli": "💻 Открыть CLI",
        "menu_clear_keyfiles": "Очистить ключевые файлы",
        "dialog_select_keyfiles": "Выберите ключевой файл(ы)",

        # Tray
        "tray_minimized_message": "Работает в фоновом режиме. Нажмите на значок в трее, чтобы открыть.",
        "tray_tooltip": "{name} ({id})",

        # Worker messages (keys for structured errors)
        "worker_mount_script_not_found": "Скрипт монтирования не найден",
        "worker_mount_success": "Том успешно смонтирован",
        "worker_mount_failed": "Ошибка монтирования: {error}",
        "worker_mount_timeout": "Время ожидания монтирования истекло",
        "worker_mount_error": "Ошибка монтирования: {error}",
        "worker_unmount_script_not_found": "Скрипт размонтирования не найден",
        "worker_unmount_success": "Том успешно размонтирован",
        "worker_unmount_failed": "Ошибка размонтирования: {error}",
        "worker_unmount_timeout": "Время ожидания размонтирования истекло",
        "worker_unmount_error": "Ошибка размонтирования: {error}",

        # Settings dialog - Tab names
        "settings_language": "Язык",
        "settings_general": "Общие",
        "settings_security": "Безопасность",
        "settings_keyfile": "Ключевой файл",
        "settings_windows": "Windows",
        "settings_unix": "Unix",
        "settings_updates": "Обновления",
        "settings_recovery": "Восстановление",
        "settings_lost_and_found": "Бюро находок",
        "settings_advanced": "Дополнительно",
        
        # Settings dialog - Tab descriptions
        "settings_general_desc": "Настройте отображаемое имя, язык и параметры темы приложения.",
        "settings_security_desc": "Установите режим шифрования и метод аутентификации для вашего защищённого диска.",
        "settings_keyfile_desc": "Управляйте путями к ключевым файлам для шифрования и GPG-аутентификации.",
        "settings_windows_desc": "Настройки для Windows, включая букву диска и расположение VeraCrypt.",
        "settings_unix_desc": "Настройки для Linux и macOS, включая каталог точки монтирования.",
        "settings_updates_desc": "Настройте автоматическую проверку обновлений и параметры сервера.",
        "settings_recovery_desc": "Настройте параметры восстановления Shamir Secret Sharing для доступа при утере ключей.",
        "settings_lost_and_found_desc": "Отображайте контактное сообщение на диске для возврата при потере.",
        "settings_advanced_desc": "Технические настройки параметров шифрования и проверки целостности.",
        
        "settings_restart_not_required": "✓ Изменения применены сразу (перезапуск не требуется)",
        "label_mode": "Режим",
        "label_encrypted_keyfile": "Зашифрованный ключевой файл",
        "label_volume_path": "Путь к тому",
        "label_mount_letter": "Буква диска",
        "label_veracrypt_path": "Путь к VeraCrypt",
        "label_mount_point": "Точка монтирования",
        "label_source_type": "Тип источника",
        "label_server_url": "URL сервера",
        "label_local_root": "Локальный корневой каталог",
        "error_invalid_mount_letter": "Буква диска должна быть одной буквой A–Z.",
        "error_save_failed": "Не удалось сохранить config.json:",
        "title_invalid_mount_letter": "Недопустимая буква диска",
        "title_save_failed": "Ошибка сохранения",

        # Popup dialogs
        "popup_keyfile_required_title": "Требуется ключевой файл",
        "popup_keyfile_required_body": "Пожалуйста, выберите ключевой файл для режима пароль + ключевой файл.",
        "popup_password_required_title": "Требуется пароль",
        "popup_password_required_body": "Пожалуйста, введите пароль VeraCrypt.",
        "popup_recovery_title": "Восстановление пароля",
        "popup_recovery_available_body": "Для этого диска доступен набор восстановления!\n\nЧтобы восстановить доступ к зашифрованному тому:\n\n1. Откройте SmartDrive CLI: python smartdrive.py\n2. Выберите пункт 6: Recovery Kit\n3. Следуйте инструкциям по восстановлению\n\nИли обратитесь к системному администратору.",
        "popup_recovery_unavailable_body": "Набор восстановления для этого диска сейчас недоступен.\n\nЧтобы настроить восстановление пароля:\n\n1. Откройте SmartDrive CLI: python smartdrive.py\n2. Выберите пункт 6: Recovery Kit\n3. Выберите 'Generate Recovery Kit'\n\nИли обратитесь к системному администратору.",
        
        # Recovery tab - Phrase input and recovery actions
        "recovery_section_title": "🔐 Аварийное восстановление",
        "recovery_instructions": "Введите вашу фразу восстановления из 24 слов для восстановления доступа к зашифрованному тому. Вы также можете указать файл контейнера восстановления, если он у вас есть.",
        "label_recovery_phrase": "Фраза восстановления (24 слова):",
        "placeholder_recovery_phrase": "Введите 24 слова через пробел...",
        "label_recovery_container": "Контейнер восстановления (необязательно):",
        "btn_browse_container": "Обзор...",
        "btn_recover_credentials": "🔓 Восстановить учётные данные",
        "recovery_status_ready": "Введите фразу восстановления и нажмите 'Восстановить учётные данные'",
        "recovery_status_validating": "Проверка фразы восстановления...",
        "recovery_status_decrypting": "Расшифровка контейнера восстановления...",
        "recovery_status_success": "✅ Восстановление успешно! Учётные данные восстановлены.",
        "recovery_status_failed": "❌ Ошибка восстановления: {error}",
        "recovery_result_title": "Восстановленные учётные данные",
        "recovery_result_password": "Пароль:",
        "recovery_result_keyfile": "Ключевой файл:",
        "recovery_result_mode": "Режим безопасности:",
        "recovery_result_copy_password": "📋 Копировать пароль",
        "recovery_result_save_keyfile": "💾 Сохранить ключевой файл",
        "recovery_copied_to_clipboard": "Пароль скопирован в буфер обмена (автоочистка через 30 секунд)",
        "recovery_keyfile_saved": "Ключевой файл сохранён в: {path}",
        "recovery_phrase_invalid": "Неверная фраза восстановления. Проверьте все 24 слова.",
        "recovery_container_not_found": "Контейнер восстановления не найден. Выберите файл контейнера.",
        "recovery_no_kit_configured": "Для этого диска не настроен набор восстановления.",
        "recovery_generate_first": "Сначала сгенерируйте набор восстановления через Настройки или CLI.",
        
        "popup_unmount_failed_title": "Ошибка размонтирования",
        "popup_mount_failed_title": "Ошибка монтирования",
        "popup_update_not_possible_title": "Обновление невозможно",
        "popup_update_confirm_title": "Подтвердить обновление",
        "popup_update_confirm_message": "Сейчас будет выполнено UPDATE ({direction}).\n\nИЗ:\n  {src_root}\n\nВ:\n  {dst_root}\n\nЭлементы:\n  - {items}\n\nМетод: {method}\n\nЭто перезапишет существующие файлы. Продолжить?",
        "popup_update_config_title": "Настройка обновления",
        "popup_update_config_body": "Источник обновления не настроен. Укажите его в Настройках.",
        "popup_update_complete_title": "Обновление завершено",
        "popup_update_complete_body": "Обновление успешно завершено. Пожалуйста, перезапустите приложение.",
        "popup_update_failed_title": "Ошибка обновления",
        "popup_update_failed_body": "Обновление не удалось:\n\n{error}",
        "popup_update_timeout_title": "Время ожидания обновления",
        "popup_update_timeout_body": "Обновление не завершилось за 120 секунд.",
        "popup_update_error_title": "Ошибка обновления",
        "popup_update_error_body": "Не удалось запустить обновление:\n\n{error}",
        "popup_cli_failed_title": "Не удалось запустить CLI",
        "popup_cli_failed_body": "Не удалось открыть CLI:\n\n{error}",

        # Update configuration error messages
        "error_update_server_url_not_configured": "URL сервера не настроен.\\n\\nОткройте Настройки и укажите URL для обновления.",
        "error_update_local_root_not_configured": "Локальная папка обновления не настроена.\\n\\nОткройте Настройки и укажите локальный путь для обновления.",
        "error_update_local_root_not_found": "Локальная папка обновления не найдена:\\n\\n{path}\\n\\nПроверьте Настройки и убедитесь, что путь указан верно.",
        "error_update_install_dir_not_found": "Каталог установки не найден:\\n\\n{path}",
        "error_update_unknown_source_type": "Неизвестный тип источника обновления: {type}",

        # Hardware key error messages
        "error_hardware_key_missing_title": "Требуется аппаратный ключ",
        "error_hardware_key_missing_body": "Аппаратный ключ (YubiKey/GPG-карта) не обнаружен. Подключите аппаратный ключ и повторите попытку.",

        # Theme names (for theme dropdown)
        "theme_green": "Зелёная (по умолчанию)",
        "theme_blue": "Синяя",
        "theme_rose": "Роза",
        "theme_slate": "Сланец",
        "label_theme": "Тема",
        
        # File explorer buttons
        "tooltip_open_launcher_drive": "Открыть диск запуска",
        "tooltip_open_mounted_volume": "Открыть смонтированный том",
        "popup_open_failed_title": "Ошибка открытия",
        "popup_open_failed_body": "Не удалось открыть файловый менеджер:\n\n{path}\n\n{error}",
        
        # Settings dialog - Additional fields (schema-driven UI)
        "label_drive_id": "ID диска",
        "label_drive_name": "Имя диска",
        "label_setup_date": "Дата настройки",
        "label_last_password_change": "Последнее изменение пароля",
        "label_last_verified": "Последняя проверка",
        "label_plain_keyfile": "Простой файл ключа",
        "label_seed_gpg_path": "Файл семени GPG",
        "label_kdf": "Функция вывода ключа",
        "label_pw_encoding": "Кодировка пароля",
        "label_recovery_enabled": "Включить набор восстановления",
        "label_recovery_share_count": "Количество частей восстановления",
        "label_recovery_threshold": "Порог восстановления",
        "label_lost_and_found_enabled": "Включить сообщение о потере",
        "label_lost_and_found_message": "Сообщение о возврате",
        "label_verification_overridden": "Проверка отменена",
        "label_integrity_signed": "Целостность подписана",
        "label_signing_key_fpr": "Отпечаток ключа подписи",
        "label_salt_b64": "Соль (Base64)",
        "label_hkdf_info": "Информация HKDF",
        "label_schema_version": "Версия схемы",
        "label_version": "Версия",
        
        # Tooltips for settings fields
        "tooltip_drive_id": "Уникальный идентификатор для этого диска (только чтение)",
        "tooltip_drive_name": "Пользовательское имя для этого диска",
        "tooltip_language": "Язык интерфейса пользователя",
        "tooltip_theme": "Цветовая схема интерфейса",
        "tooltip_mode": "Режим безопасности: только пароль, файл ключа или YubiKey/GPG",
        "tooltip_encrypted_keyfile": "Путь к зашифрованному GPG файлу ключа (для режимов GPG)",
        "tooltip_plain_keyfile": "Путь к незашифрованному файлу ключа (для простого режима файла ключа)",
        "tooltip_seed_gpg_path": "Путь к файлу семени GPG для вывода пароля",
        "tooltip_kdf": "Функция вывода ключа для режима пароля GPG",
        "tooltip_pw_encoding": "Кодировка символов для пароля (рекомендуется UTF-8)",
        "tooltip_windows_volume_path": "GUID тома Windows или путь к устройству",
        "tooltip_mount_letter": "Буква диска для монтирования (A-Z)",
        "tooltip_veracrypt_path": "Путь к исполняемому файлу VeraCrypt.exe",
        "tooltip_unix_volume_path": "Путь к устройству Unix (например, /dev/sdb2)",
        "tooltip_mount_point": "Каталог точки монтирования Unix",
        "tooltip_recovery_enabled": "Включить генерацию аварийного набора восстановления",
        "tooltip_recovery_share_count": "Количество частей восстановления для генерации",
        "tooltip_recovery_threshold": "Минимальное количество частей, необходимых для восстановления",
        "tooltip_lost_and_found_enabled": "Включить сообщение о возврате при потере диска",
        "tooltip_lost_and_found_message": "Сообщение, отображаемое при нахождении диска",
        "tooltip_source_type": "Источник обновления: локальный каталог или URL сервера",
        "tooltip_server_url": "URL сервера для обновлений",
        "tooltip_local_root": "Локальный каталог, содержащий файлы обновления",
        "tooltip_verification_overridden": "Обойти проверку целостности (опасно!)",
        "tooltip_integrity_signed": "Целостность диска была криптографически подписана",
        "tooltip_signing_key_fpr": "Отпечаток ключа GPG, используемого для подписи",
        "tooltip_salt_b64": "Криптографическая соль для вывода ключа",
        "tooltip_hkdf_info": "Контекстная строка для вывода ключа HKDF",
    },
    "zh": {
        # Window titles
        "window_title": "KeyDrive",
        "settings_window_title": "设置",
        
        # Button labels
        "btn_mount": "🔓 挂载",
        "btn_unmount": "🔒 卸载",
        "btn_cancel_auth": "❌ 取消",
        "btn_confirm_mount": "✅ 确认",
        "btn_tools": "⚙️",
        "btn_close": "✕",
        "btn_save": "保存",
        "btn_cancel": "取消",
        
        # Status messages
        "status_config_not_found": "未找到配置",
        "status_volume_mounted": "卷已挂载",
        "status_volume_not_mounted": "卷未挂载",
        "status_mounting": "⏳ 正在挂载卷...",
        "status_mounting_gpg": "⏳ 正在挂载卷（GPG 认证）...",
        "status_unmounting": "⏳ 正在卸载卷...",
        "status_mount_success": "✅ 卷挂载成功",
        "status_mount_failed": "❌ 挂载失败",
        "status_unmount_success": "✅ 卷卸载成功",
        "status_unmount_failed": "❌ 卸载失败",
        
        # Info labels
        "info_unavailable": "信息不可用",
        "keyfile_selected_one": "已选择 1 个密钥文件",
        "keyfile_selected_many": "已选择 {count} 个密钥文件",
        "keyfile_drop_hint": "将密钥文件拖到此处或点击浏览",
        "keyfile_drop_supports_multiple": "支持多个密钥文件",
        "label_show_password": "显示密码",
        
        # Size formatting
        "size_free": "可用：{size}",
        
        # Icons/placeholders
        "icon_drive": "🚀",
        
        # Tooltips
        "tooltip_exit": "退出 SmartDrive",
        "tooltip_settings": "高级工具和设置",
        
        # Labels
        "label_product_name": "产品名称",
        "label_preview": "预览：",
        "label_password": "密码：",
        "label_keyfile": "密钥文件：",
        "label_hardware_key_hint": "💡 认证可能需要硬件密钥",
        "label_forgot_password": "忘记密码？",
        
        # Placeholder text
        "placeholder_password": "请输入你的 VeraCrypt 密码...",
        
        # Menu items
        "menu_settings": "⚙️ 设置",
        "menu_rekey": "🔑 更改密码/密钥文件",
        "menu_update": "⬇️ 更新脚本",
        "menu_recovery": "💾 恢复工具包",
        "menu_about": "ℹ️ 关于",
        "menu_cli": "💻 打开 CLI",
        "menu_clear_keyfiles": "清除密钥文件",
        "dialog_select_keyfiles": "选择密钥文件（可多选）",
        
        # Tray
        "tray_minimized_message": "正在后台运行。点击托盘图标打开。",
        "tray_tooltip": "{name} ({id})",
        
        # Worker messages (keys for structured errors)
        "worker_mount_script_not_found": "未找到挂载脚本",
        "worker_mount_success": "卷挂载成功",
        "worker_mount_failed": "挂载失败：{error}",
        "worker_mount_timeout": "挂载操作超时",
        "worker_mount_error": "挂载错误：{error}",
        "worker_unmount_script_not_found": "未找到卸载脚本",
        "worker_unmount_success": "卷卸载成功",
        "worker_unmount_failed": "卸载失败：{error}",
        "worker_unmount_timeout": "卸载操作超时",
        "worker_unmount_error": "卸载错误：{error}",
        
        # Settings dialog - Tab names
        "settings_language": "语言",
        "settings_general": "常规",
        "settings_security": "安全",
        "settings_keyfile": "密钥文件",
        "settings_windows": "Windows",
        "settings_unix": "Unix",
        "settings_updates": "更新",
        "settings_recovery": "恢复",
        "settings_lost_and_found": "失物招领",
        "settings_advanced": "高级",
        
        # Settings dialog - Tab descriptions
        "settings_general_desc": "配置显示名称、语言和主题首选项。",
        "settings_security_desc": "设置安全驱动器的加密模式和身份验证方法。",
        "settings_keyfile_desc": "管理用于加密和 GPG 身份验证的密钥文件路径。",
        "settings_windows_desc": "Windows 特定设置，包括挂载盘符和 VeraCrypt 位置。",
        "settings_unix_desc": "Linux 和 macOS 设置，包括挂载点目录。",
        "settings_updates_desc": "配置自动更新检查和服务器设置。",
        "settings_recovery_desc": "设置 Shamir 秘密共享恢复选项，以便在密钥丢失时恢复访问。",
        "settings_lost_and_found_desc": "在驱动器上显示联系信息，以便丢失时归还。",
        "settings_advanced_desc": "加密参数和完整性验证的技术设置。",
        
        "settings_restart_not_required": "✓ 更改已立即应用（无需重启）",
        "label_mode": "模式",
        "label_encrypted_keyfile": "加密的密钥文件",
        "label_volume_path": "卷路径",
        "label_mount_letter": "挂载盘符",
        "label_veracrypt_path": "VeraCrypt 路径",
        "label_mount_point": "挂载点",
        "label_source_type": "来源类型",
        "label_server_url": "服务器 URL",
        "label_local_root": "本地根目录",
        "error_invalid_mount_letter": "盘符必须是单个 A–Z 字符。",
        "error_save_failed": "无法保存 config.json：",
        "title_invalid_mount_letter": "无效盘符",
        "title_save_failed": "保存失败",
        
        # Popup dialogs
        "popup_keyfile_required_title": "需要密钥文件",
        "popup_keyfile_required_body": "在“密码 + 密钥文件”模式下请选择密钥文件。",
        "popup_password_required_title": "需要密码",
        "popup_password_required_body": "请输入你的 VeraCrypt 密码。",
        "popup_recovery_title": "密码恢复",
        "popup_recovery_available_body": "此驱动器有可用的恢复工具包！\n\n要恢复对加密卷的访问：\n\n1. 使用 SmartDrive CLI：python smartdrive.py\n2. 选择选项 6：恢复工具包\n3. 按照恢复说明操作\n\n或联系系统管理员。",
        "popup_recovery_unavailable_body": "此驱动器当前没有可用的恢复工具包。\n\n要设置密码恢复：\n\n1. 使用 SmartDrive CLI：python smartdrive.py\n2. 选择选项 6：恢复工具包\n3. 选择 'Generate Recovery Kit'\n\n或联系系统管理员。",
        
        # Recovery tab - Phrase input and recovery actions
        "recovery_section_title": "🔐 紧急恢复",
        "recovery_instructions": "输入您的 24 个单词的恢复短语以恢复对加密卷的访问。如果您有恢复容器文件，也可以在这里提供。",
        "label_recovery_phrase": "恢复短语（24 个单词）：",
        "placeholder_recovery_phrase": "输入 24 个以空格分隔的单词...",
        "label_recovery_container": "恢复容器（可选）：",
        "btn_browse_container": "浏览...",
        "btn_recover_credentials": "🔓 恢复凭证",
        "recovery_status_ready": "输入恢复短语并点击「恢复凭证」",
        "recovery_status_validating": "正在验证恢复短语...",
        "recovery_status_decrypting": "正在解密恢复容器...",
        "recovery_status_success": "✅ 恢复成功！凭证已恢复。",
        "recovery_status_failed": "❌ 恢复失败：{error}",
        "recovery_result_title": "已恢复的凭证",
        "recovery_result_password": "密码：",
        "recovery_result_keyfile": "密钥文件：",
        "recovery_result_mode": "安全模式：",
        "recovery_result_copy_password": "📋 复制密码",
        "recovery_result_save_keyfile": "💾 保存密钥文件",
        "recovery_copied_to_clipboard": "密码已复制到剪贴板（30 秒后自动清除）",
        "recovery_keyfile_saved": "密钥文件已保存到：{path}",
        "recovery_phrase_invalid": "恢复短语无效。请检查全部 24 个单词。",
        "recovery_container_not_found": "未找到恢复容器。请选择容器文件。",
        "recovery_no_kit_configured": "此驱动器未配置恢复工具包。",
        "recovery_generate_first": "请先通过设置或 CLI 生成恢复工具包。",
        
        "popup_unmount_failed_title": "卸载失败",
        "popup_mount_failed_title": "挂载失败",
        "popup_update_not_possible_title": "无法更新",
        "popup_update_confirm_title": "确认更新",
        "popup_update_confirm_message": "即将运行 UPDATE ({direction}).\n\n来源:\n  {src_root}\n\n目标:\n  {dst_root}\n\n项目:\n  - {items}\n\n方式: {method}\n\n这将覆盖现有文件。继续？",
        "popup_update_config_title": "更新配置",
        "popup_update_config_body": "未配置更新来源。请在设置中进行配置。",
        "popup_update_complete_title": "更新完成",
        "popup_update_complete_body": "更新成功完成。请重启应用程序。",
        "popup_update_failed_title": "更新失败",
        "popup_update_failed_body": "更新失败：\n\n{error}",
        "popup_update_timeout_title": "更新超时",
        "popup_update_timeout_body": "更新在 120 秒内未完成。",
        "popup_update_error_title": "更新错误",
        "popup_update_error_body": "无法运行更新：\n\n{error}",
        "popup_cli_failed_title": "CLI 启动失败",
        "popup_cli_failed_body": "无法打开 CLI：\n\n{error}",
        
        # Update configuration error messages
        "error_update_server_url_not_configured": "未配置服务器 URL。\n\n请前往设置配置更新 URL。",
        "error_update_local_root_not_configured": "未配置本地更新目录。\n\n请前往设置配置本地更新根目录。",
        "error_update_local_root_not_found": "未找到本地更新目录：\n\n{path}\n\n请检查设置以验证路径。",
        "error_update_install_dir_not_found": "未找到安装目录：\n\n{path}",
        "error_update_unknown_source_type": "未知的更新来源类型：{type}",
        
        # Hardware key error messages
        "error_hardware_key_missing_title": "需要硬件密钥",
        "error_hardware_key_missing_body": "未检测到硬件密钥（YubiKey/GPG 卡）。请插入硬件密钥后重试。",
        
        # Theme names (for theme dropdown)
        "theme_green": "绿色（默认）",
        "theme_blue": "蓝色",
        "theme_rose": "玫瑰",
        "theme_slate": "石板",
        "label_theme": "主题",
        
        # File explorer buttons
        "tooltip_open_launcher_drive": "打开启动器驱动器",
        "tooltip_open_mounted_volume": "打开已挂载的卷",
        "popup_open_failed_title": "打开失败",
        "popup_open_failed_body": "无法打开文件管理器:\n\n{path}\n\n{error}",
        
        # Settings dialog - Additional fields (schema-driven UI)
        "label_drive_id": "驱动器 ID",
        "label_drive_name": "驱动器名称",
        "label_setup_date": "设置日期",
        "label_last_password_change": "上次密码更改",
        "label_last_verified": "上次验证",
        "label_plain_keyfile": "普通密钥文件",
        "label_seed_gpg_path": "GPG 种子文件",
        "label_kdf": "密钥派生函数",
        "label_pw_encoding": "密码编码",
        "label_recovery_enabled": "启用恢复工具包",
        "label_recovery_share_count": "恢复份额数量",
        "label_recovery_threshold": "恢复阈值",
        "label_lost_and_found_enabled": "启用失物招领消息",
        "label_lost_and_found_message": "返回消息",
        "label_verification_overridden": "已覆盖验证",
        "label_integrity_signed": "完整性已签名",
        "label_signing_key_fpr": "签名密钥指纹",
        "label_salt_b64": "盐（Base64）",
        "label_hkdf_info": "HKDF 信息",
        "label_schema_version": "模式版本",
        "label_version": "版本",
        
        # Tooltips for settings fields
        "tooltip_drive_id": "此驱动器的唯一标识符（只读）",
        "tooltip_drive_name": "此驱动器的自定义名称",
        "tooltip_language": "用户界面语言",
        "tooltip_theme": "界面配色方案",
        "tooltip_mode": "安全模式：仅密码、密钥文件或 YubiKey/GPG",
        "tooltip_encrypted_keyfile": "GPG 加密的密钥文件路径（用于 GPG 模式）",
        "tooltip_plain_keyfile": "未加密的密钥文件路径（用于普通密钥文件模式）",
        "tooltip_seed_gpg_path": "用于密码派生的 GPG 种子文件路径",
        "tooltip_kdf": "GPG 密码模式的密钥派生函数",
        "tooltip_pw_encoding": "密码的字符编码（推荐 UTF-8）",
        "tooltip_windows_volume_path": "Windows 卷 GUID 或设备路径",
        "tooltip_mount_letter": "挂载为驱动器号（A-Z）",
        "tooltip_veracrypt_path": "VeraCrypt.exe 可执行文件的路径",
        "tooltip_unix_volume_path": "Unix 设备路径（例如 /dev/sdb2）",
        "tooltip_mount_point": "Unix 挂载点目录",
        "tooltip_recovery_enabled": "启用紧急恢复工具包生成",
        "tooltip_recovery_share_count": "要生成的恢复份额数量",
        "tooltip_recovery_threshold": "恢复所需的最少份额数",
        "tooltip_lost_and_found_enabled": "如果驱动器丢失，启用返回消息",
        "tooltip_lost_and_found_message": "找到驱动器时显示的消息",
        "tooltip_source_type": "更新源：本地目录或服务器 URL",
        "tooltip_server_url": "更新的服务器 URL",
        "tooltip_local_root": "包含更新文件的本地目录",
        "tooltip_verification_overridden": "绕过完整性验证（危险！）",
        "tooltip_integrity_signed": "驱动器完整性已进行加密签名",
        "tooltip_signing_key_fpr": "用于签名的 GPG 密钥指纹",
        "tooltip_salt_b64": "用于密钥派生的加密盐",
        "tooltip_hkdf_info": "HKDF 密钥派生的上下文字符串",
    },
}


# =============================================================================
# Translation Function
# =============================================================================

def tr(key: str, *, lang: str = "en", **kwargs) -> str:
    """
    Translate a GUI string key to the specified language.
    
    Args:
        key: Translation key (e.g., "btn_mount")
        lang: Target language code (default: "en")
        **kwargs: Format arguments for string interpolation
    
    Returns:
        Translated string
    
    Raises:
        KeyError: If key is missing in both selected lang and 'en' fallback
    
    Examples:
        tr("btn_mount")  # "🔓 Mount"
        tr("keyfile_selected_many", count=3)  # "3 keyfiles selected"
    """
    # Try selected language
    if lang in TRANSLATIONS and key in TRANSLATIONS[lang]:
        template = TRANSLATIONS[lang][key]
        return template.format(**kwargs) if kwargs else template
    
    # Fallback to English
    if key in TRANSLATIONS.get("en", {}):
        template = TRANSLATIONS["en"][key]
        return template.format(**kwargs) if kwargs else template
    
    # Hard fail - missing key even in English
    raise KeyError(
        f"Translation key '{key}' not found in language '{lang}' "
        f"nor in fallback language 'en'. This is a programming error."
    )


# =============================================================================
# Validation Helper
# =============================================================================

def validate_keys(used_keys: set) -> None:
    """
    Validate that all used translation keys exist in English fallback.
    
    Args:
        used_keys: Set of all keys used by GUI code
    
    Raises:
        KeyError: If any key is missing from 'en' translation table
    """
    en_keys = set(TRANSLATIONS.get("en", {}).keys())
    missing = used_keys - en_keys
    
    if missing:
        raise KeyError(
            f"Missing translation keys in 'en' fallback: {sorted(missing)}"
        )
