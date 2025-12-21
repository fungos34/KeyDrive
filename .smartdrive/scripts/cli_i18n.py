#!/usr/bin/env python3
"""
CLI Internationalization (i18n) Module

SINGLE SOURCE OF TRUTH for all CLI-visible text labels.
Shares the same language configuration as the GUI.

This module provides i18n support for the smartdrive.py CLI tool,
loading the language preference from config.json.

Usage:
    from cli_i18n import tr, init_cli_i18n, get_cli_lang
    from core.paths import Paths
    
    # Initialize with config path
    drive_root = Path("G:\\")
    init_cli_i18n(Paths.config_file(drive_root))
    
    # Get translated string
    print(tr("cli_welcome"))
    
    # With parameters
    print(tr("cli_mount_success", drive="V:"))
"""

import json
import sys
from pathlib import Path
from typing import Dict, Optional

# =============================================================================
# Core module imports for ConfigKeys
# =============================================================================
_script_dir = Path(__file__).resolve().parent

if _script_dir.parent.name == ".smartdrive":
    _deploy_root = _script_dir.parent
    if str(_deploy_root) not in sys.path:
        sys.path.insert(0, str(_deploy_root))
else:
    _project_root = _script_dir.parent
    if str(_project_root) not in sys.path:
        sys.path.insert(0, str(_project_root))

try:
    from core.constants import ConfigKeys
except ImportError:
    # Fallback if core module not available
    class ConfigKeys:
        GUI_LANG = "gui_lang"


# =============================================================================
# Global State
# =============================================================================

_current_lang: str = "en"

# =============================================================================
# CLI-Specific Translation Table
# =============================================================================
# These translations are for CLI-specific strings.
# Common strings shared with GUI should reference gui_i18n.TRANSLATIONS

CLI_TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "en": {
        # Banner and welcome
        "cli_banner": "╔═══════════════════════════════════════════════════════════════════════╗",
        "cli_banner_title": "║                        SMARTDRIVE CLI                                 ║",
        "cli_banner_bottom": "╚═══════════════════════════════════════════════════════════════════════╝",
        "cli_welcome": "Welcome to {Branding.APP_NAME} Command Line Interface",
        "cli_version": "Version: {version}",
        # Menu items
        "cli_menu_mount": "Mount encrypted volume",
        "cli_menu_unmount": "Unmount volume",
        "cli_menu_status": "Show status",
        "cli_menu_settings": "Settings",
        "cli_menu_recovery": "Recovery tools",
        "cli_menu_quit": "Exit",
        "cli_menu_prompt": "Select an option",
        # Status messages
        "cli_status_mounted": "Volume is mounted at {drive}",
        "cli_status_unmounted": "Volume is not mounted",
        "cli_status_unknown": "Unable to determine mount status",
        # Mount/unmount
        "cli_mount_starting": "Mounting encrypted volume...",
        "cli_mount_success": "✓ Volume mounted successfully at {drive}",
        "cli_mount_failed": "✗ Mount failed: {error}",
        "cli_unmount_starting": "Unmounting volume...",
        "cli_unmount_success": "✓ Volume unmounted successfully",
        "cli_unmount_failed": "✗ Unmount failed: {error}",
        # Prompts
        "cli_press_enter": "Press Enter to continue...",
        "cli_confirm_yes_no": "[y/N]",
        "cli_password_prompt": "Enter VeraCrypt password:",
        "cli_pin_prompt": "Enter YubiKey PIN:",
        # Errors
        "cli_error_config_not_found": "Configuration file not found: {path}",
        "cli_error_invalid_option": "Invalid option. Please try again.",
        # Recovery
        "cli_recovery_generate": "Generate recovery kit",
        "cli_recovery_recover": "Recover access using recovery phrase",
        "cli_recovery_status": "View recovery status",
        # Setup
        "cli_setup_title": "{Branding.APP_NAME} Setup",
        "cli_setup_complete": "Setup completed successfully!",
        "cli_setup_failed": "Setup failed: {error}",
        # Language
        "cli_lang_current": "Current language: {lang}",
        "cli_lang_changed": "Language changed to: {lang}",
    },
    "de": {
        "cli_banner": "╔═══════════════════════════════════════════════════════════════════════╗",
        "cli_banner_title": "║                        SMARTDRIVE CLI                                 ║",
        "cli_banner_bottom": "╚═══════════════════════════════════════════════════════════════════════╝",
        "cli_welcome": "Willkommen bei {Branding.APP_NAME} Kommandozeilen-Schnittstelle",
        "cli_version": "Version: {version}",
        "cli_menu_mount": "Verschlüsseltes Volumen einbinden",
        "cli_menu_unmount": "Volumen aushängen",
        "cli_menu_status": "Status anzeigen",
        "cli_menu_settings": "Einstellungen",
        "cli_menu_recovery": "Wiederherstellungstools",
        "cli_menu_quit": "Beenden",
        "cli_menu_prompt": "Option wählen",
        "cli_status_mounted": "Volumen ist eingebunden unter {drive}",
        "cli_status_unmounted": "Volumen ist nicht eingebunden",
        "cli_status_unknown": "Mount-Status kann nicht ermittelt werden",
        "cli_mount_starting": "Binde verschlüsseltes Volumen ein...",
        "cli_mount_success": "✓ Volumen erfolgreich eingebunden unter {drive}",
        "cli_mount_failed": "✗ Einbinden fehlgeschlagen: {error}",
        "cli_unmount_starting": "Hänge Volumen aus...",
        "cli_unmount_success": "✓ Volumen erfolgreich ausgehängt",
        "cli_unmount_failed": "✗ Aushängen fehlgeschlagen: {error}",
        "cli_press_enter": "Drücken Sie Enter um fortzufahren...",
        "cli_confirm_yes_no": "[j/N]",
        "cli_password_prompt": "VeraCrypt-Passwort eingeben:",
        "cli_pin_prompt": "YubiKey-PIN eingeben:",
        "cli_error_config_not_found": "Konfigurationsdatei nicht gefunden: {path}",
        "cli_error_invalid_option": "Ungültige Option. Bitte erneut versuchen.",
        "cli_recovery_generate": "Wiederherstellungs-Kit erstellen",
        "cli_recovery_recover": "Zugang mit Wiederherstellungsphrase wiederherstellen",
        "cli_recovery_status": "Wiederherstellungsstatus anzeigen",
        "cli_setup_title": "{Branding.APP_NAME} Einrichtung",
        "cli_setup_complete": "Einrichtung erfolgreich abgeschlossen!",
        "cli_setup_failed": "Einrichtung fehlgeschlagen: {error}",
        "cli_lang_current": "Aktuelle Sprache: {lang}",
        "cli_lang_changed": "Sprache geändert auf: {lang}",
    },
    "es": {
        "cli_banner": "╔═══════════════════════════════════════════════════════════════════════╗",
        "cli_banner_title": "║                        SMARTDRIVE CLI                                 ║",
        "cli_banner_bottom": "╚═══════════════════════════════════════════════════════════════════════╝",
        "cli_welcome": "Bienvenido a la interfaz de línea de comandos de {Branding.APP_NAME}",
        "cli_version": "Versión: {version}",
        "cli_menu_mount": "Montar volumen cifrado",
        "cli_menu_unmount": "Desmontar volumen",
        "cli_menu_status": "Mostrar estado",
        "cli_menu_settings": "Configuración",
        "cli_menu_recovery": "Herramientas de recuperación",
        "cli_menu_quit": "Salir",
        "cli_menu_prompt": "Seleccione una opción",
        "cli_status_mounted": "El volumen está montado en {drive}",
        "cli_status_unmounted": "El volumen no está montado",
        "cli_status_unknown": "No se puede determinar el estado de montaje",
        "cli_mount_starting": "Montando volumen cifrado...",
        "cli_mount_success": "✓ Volumen montado correctamente en {drive}",
        "cli_mount_failed": "✗ Error al montar: {error}",
        "cli_unmount_starting": "Desmontando volumen...",
        "cli_unmount_success": "✓ Volumen desmontado correctamente",
        "cli_unmount_failed": "✗ Error al desmontar: {error}",
        "cli_press_enter": "Presione Enter para continuar...",
        "cli_confirm_yes_no": "[s/N]",
        "cli_password_prompt": "Introduzca la contraseña de VeraCrypt:",
        "cli_pin_prompt": "Introduzca el PIN del YubiKey:",
        "cli_error_config_not_found": "Archivo de configuración no encontrado: {path}",
        "cli_error_invalid_option": "Opción inválida. Por favor, inténtelo de nuevo.",
        "cli_recovery_generate": "Generar kit de recuperación",
        "cli_recovery_recover": "Recuperar acceso usando frase de recuperación",
        "cli_recovery_status": "Ver estado de recuperación",
        "cli_setup_title": "Configuración de {Branding.APP_NAME}",
        "cli_setup_complete": "¡Configuración completada correctamente!",
        "cli_setup_failed": "Configuración fallida: {error}",
        "cli_lang_current": "Idioma actual: {lang}",
        "cli_lang_changed": "Idioma cambiado a: {lang}",
    },
    "fr": {
        "cli_banner": "╔═══════════════════════════════════════════════════════════════════════╗",
        "cli_banner_title": "║                        SMARTDRIVE CLI                                 ║",
        "cli_banner_bottom": "╚═══════════════════════════════════════════════════════════════════════╝",
        "cli_welcome": "Bienvenue dans l'interface en ligne de commande {Branding.APP_NAME}",
        "cli_version": "Version: {version}",
        "cli_menu_mount": "Monter le volume chiffré",
        "cli_menu_unmount": "Démonter le volume",
        "cli_menu_status": "Afficher l'état",
        "cli_menu_settings": "Paramètres",
        "cli_menu_recovery": "Outils de récupération",
        "cli_menu_quit": "Quitter",
        "cli_menu_prompt": "Sélectionnez une option",
        "cli_status_mounted": "Le volume est monté sur {drive}",
        "cli_status_unmounted": "Le volume n'est pas monté",
        "cli_status_unknown": "Impossible de déterminer l'état du montage",
        "cli_mount_starting": "Montage du volume chiffré...",
        "cli_mount_success": "✓ Volume monté avec succès sur {drive}",
        "cli_mount_failed": "✗ Échec du montage: {error}",
        "cli_unmount_starting": "Démontage du volume...",
        "cli_unmount_success": "✓ Volume démonté avec succès",
        "cli_unmount_failed": "✗ Échec du démontage: {error}",
        "cli_press_enter": "Appuyez sur Entrée pour continuer...",
        "cli_confirm_yes_no": "[o/N]",
        "cli_password_prompt": "Entrez le mot de passe VeraCrypt:",
        "cli_pin_prompt": "Entrez le code PIN YubiKey:",
        "cli_error_config_not_found": "Fichier de configuration non trouvé: {path}",
        "cli_error_invalid_option": "Option invalide. Veuillez réessayer.",
        "cli_recovery_generate": "Générer un kit de récupération",
        "cli_recovery_recover": "Récupérer l'accès avec la phrase de récupération",
        "cli_recovery_status": "Voir l'état de récupération",
        "cli_setup_title": "Configuration de {Branding.APP_NAME}",
        "cli_setup_complete": "Configuration terminée avec succès!",
        "cli_setup_failed": "Configuration échouée: {error}",
        "cli_lang_current": "Langue actuelle: {lang}",
        "cli_lang_changed": "Langue changée en: {lang}",
    },
    "bs": {
        "cli_banner": "╔═══════════════════════════════════════════════════════════════════════╗",
        "cli_banner_title": "║                        SMARTDRIVE CLI                                 ║",
        "cli_banner_bottom": "╚═══════════════════════════════════════════════════════════════════════╝",
        "cli_welcome": "Dobrodošli u {Branding.APP_NAME} komandnu liniju",
        "cli_version": "Verzija: {version}",
        "cli_menu_mount": "Montiraj šifrovani volumen",
        "cli_menu_unmount": "Demontiraj volumen",
        "cli_menu_status": "Prikaži status",
        "cli_menu_settings": "Postavke",
        "cli_menu_recovery": "Alati za oporavak",
        "cli_menu_quit": "Izlaz",
        "cli_menu_prompt": "Odaberite opciju",
        "cli_status_mounted": "Volumen je montiran na {drive}",
        "cli_status_unmounted": "Volumen nije montiran",
        "cli_status_unknown": "Nije moguće odrediti status montiranja",
        "cli_mount_starting": "Montiranje šifrovanog volumena...",
        "cli_mount_success": "✓ Volumen uspješno montiran na {drive}",
        "cli_mount_failed": "✗ Montiranje neuspješno: {error}",
        "cli_unmount_starting": "Demontiranje volumena...",
        "cli_unmount_success": "✓ Volumen uspješno demontiran",
        "cli_unmount_failed": "✗ Demontiranje neuspješno: {error}",
        "cli_press_enter": "Pritisnite Enter za nastavak...",
        "cli_confirm_yes_no": "[d/N]",
        "cli_password_prompt": "Unesite VeraCrypt lozinku:",
        "cli_pin_prompt": "Unesite YubiKey PIN:",
        "cli_error_config_not_found": "Konfiguracijska datoteka nije pronađena: {path}",
        "cli_error_invalid_option": "Nevažeća opcija. Pokušajte ponovo.",
        "cli_recovery_generate": "Generiši kit za oporavak",
        "cli_recovery_recover": "Oporavi pristup koristeći frazu za oporavak",
        "cli_recovery_status": "Prikaži status oporavka",
        "cli_setup_title": "{Branding.APP_NAME} Podešavanje",
        "cli_setup_complete": "Podešavanje uspješno završeno!",
        "cli_setup_failed": "Podešavanje neuspješno: {error}",
        "cli_lang_current": "Trenutni jezik: {lang}",
        "cli_lang_changed": "Jezik promijenjen na: {lang}",
    },
    "ru": {
        "cli_banner": "╔═══════════════════════════════════════════════════════════════════════╗",
        "cli_banner_title": "║                        SMARTDRIVE CLI                                 ║",
        "cli_banner_bottom": "╚═══════════════════════════════════════════════════════════════════════╝",
        "cli_welcome": "Добро пожаловать в командную строку {Branding.APP_NAME}",
        "cli_version": "Версия: {version}",
        "cli_menu_mount": "Подключить зашифрованный том",
        "cli_menu_unmount": "Отключить том",
        "cli_menu_status": "Показать статус",
        "cli_menu_settings": "Настройки",
        "cli_menu_recovery": "Инструменты восстановления",
        "cli_menu_quit": "Выход",
        "cli_menu_prompt": "Выберите опцию",
        "cli_status_mounted": "Том подключен к {drive}",
        "cli_status_unmounted": "Том не подключен",
        "cli_status_unknown": "Невозможно определить статус подключения",
        "cli_mount_starting": "Подключение зашифрованного тома...",
        "cli_mount_success": "✓ Том успешно подключен к {drive}",
        "cli_mount_failed": "✗ Подключение не удалось: {error}",
        "cli_unmount_starting": "Отключение тома...",
        "cli_unmount_success": "✓ Том успешно отключен",
        "cli_unmount_failed": "✗ Отключение не удалось: {error}",
        "cli_press_enter": "Нажмите Enter для продолжения...",
        "cli_confirm_yes_no": "[д/Н]",
        "cli_password_prompt": "Введите пароль VeraCrypt:",
        "cli_pin_prompt": "Введите PIN-код YubiKey:",
        "cli_error_config_not_found": "Файл конфигурации не найден: {path}",
        "cli_error_invalid_option": "Неверная опция. Попробуйте еще раз.",
        "cli_recovery_generate": "Создать комплект восстановления",
        "cli_recovery_recover": "Восстановить доступ с помощью фразы восстановления",
        "cli_recovery_status": "Просмотреть статус восстановления",
        "cli_setup_title": "Настройка {Branding.APP_NAME}",
        "cli_setup_complete": "Настройка успешно завершена!",
        "cli_setup_failed": "Настройка не удалась: {error}",
        "cli_lang_current": "Текущий язык: {lang}",
        "cli_lang_changed": "Язык изменен на: {lang}",
    },
    "zh": {
        "cli_banner": "╔═══════════════════════════════════════════════════════════════════════╗",
        "cli_banner_title": "║                        SMARTDRIVE CLI                                 ║",
        "cli_banner_bottom": "╚═══════════════════════════════════════════════════════════════════════╝",
        "cli_welcome": "欢迎使用 {Branding.APP_NAME} 命令行界面",
        "cli_version": "版本: {version}",
        "cli_menu_mount": "挂载加密卷",
        "cli_menu_unmount": "卸载卷",
        "cli_menu_status": "显示状态",
        "cli_menu_settings": "设置",
        "cli_menu_recovery": "恢复工具",
        "cli_menu_quit": "退出",
        "cli_menu_prompt": "选择一个选项",
        "cli_status_mounted": "卷已挂载到 {drive}",
        "cli_status_unmounted": "卷未挂载",
        "cli_status_unknown": "无法确定挂载状态",
        "cli_mount_starting": "正在挂载加密卷...",
        "cli_mount_success": "✓ 卷已成功挂载到 {drive}",
        "cli_mount_failed": "✗ 挂载失败: {error}",
        "cli_unmount_starting": "正在卸载卷...",
        "cli_unmount_success": "✓ 卷已成功卸载",
        "cli_unmount_failed": "✗ 卸载失败: {error}",
        "cli_press_enter": "按 Enter 继续...",
        "cli_confirm_yes_no": "[是/否]",
        "cli_password_prompt": "输入 VeraCrypt 密码:",
        "cli_pin_prompt": "输入 YubiKey PIN:",
        "cli_error_config_not_found": "未找到配置文件: {path}",
        "cli_error_invalid_option": "无效选项。请重试。",
        "cli_recovery_generate": "生成恢复套件",
        "cli_recovery_recover": "使用恢复短语恢复访问",
        "cli_recovery_status": "查看恢复状态",
        "cli_setup_title": "{Branding.APP_NAME} 设置",
        "cli_setup_complete": "设置成功完成！",
        "cli_setup_failed": "设置失败: {error}",
        "cli_lang_current": "当前语言: {lang}",
        "cli_lang_changed": "语言已更改为: {lang}",
    },
}

# =============================================================================
# API Functions
# =============================================================================


def init_cli_i18n(config_path: Optional[Path] = None) -> str:
    """
    Initialize CLI i18n by loading language from config.

    Args:
        config_path: Path to config.json (optional)

    Returns:
        The language code that was loaded
    """
    global _current_lang

    # Try to load language from config
    if config_path and config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            lang = config.get(ConfigKeys.GUI_LANG, "en")
            if lang in CLI_TRANSLATIONS:
                _current_lang = lang
            else:
                _current_lang = "en"
        except Exception:
            _current_lang = "en"
    else:
        _current_lang = "en"

    return _current_lang


def get_cli_lang() -> str:
    """Get current CLI language code."""
    return _current_lang


def set_cli_lang(lang: str) -> None:
    """Set CLI language code."""
    global _current_lang
    if lang in CLI_TRANSLATIONS:
        _current_lang = lang


def tr(key: str, **kwargs) -> str:
    """
    Get translated string for current language.

    Args:
        key: Translation key
        **kwargs: Format parameters for the string

    Returns:
        Translated string, or key if not found
    """
    lang = _current_lang

    # Look up in current language
    if lang in CLI_TRANSLATIONS and key in CLI_TRANSLATIONS[lang]:
        template = CLI_TRANSLATIONS[lang][key]
        try:
            return template.format(**kwargs) if kwargs else template
        except KeyError:
            return template

    # Fallback to English
    if key in CLI_TRANSLATIONS.get("en", {}):
        template = CLI_TRANSLATIONS["en"][key]
        try:
            return template.format(**kwargs) if kwargs else template
        except KeyError:
            return template

    # Key not found - return key itself
    return f"[{key}]"


def get_available_languages() -> Dict[str, str]:
    """Get dict of available language codes and names."""
    return {
        "en": "English",
        "de": "Deutsch",
        "bs": "Bosanski",
        "es": "Español",
        "fr": "Français",
        "ru": "Русский",
        "zh": "中文",
    }
