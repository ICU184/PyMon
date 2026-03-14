"""Main application window."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from PySide6.QtCore import QByteArray, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QScrollArea,
    QSplitter,
    QStatusBar,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pymon.api.esi_client import ESIClient
from pymon.api.status import StatusAPI
from pymon.auth.callback_server import CallbackServer
from pymon.auth.sso import EVEAuth
from pymon.auth.token_manager import TokenManager
from pymon.core.config import Config
from pymon.core.database import Database
from pymon.sde.database import SDEDatabase
from pymon.sde.updater import SDEDownloadThread, SDEUpdateDialog
from pymon.services.calendar_export import export_ics_file
from pymon.services.character_service import CharacterService
from pymon.services.cloud_sync import CloudSync
from pymon.services.email_notifier import EmailNotifier
from pymon.services.name_resolver import NameResolver
from pymon.services.notification_parser import get_notification_category, parse_notification_type
from pymon.services.update_checker import UpdateCheckThread, UpdateDialog
from pymon.ui.api_tester_widget import APITesterWidget
from pymon.ui.certificate_browser_widget import CertificateBrowserWidget
from pymon.ui.character_comparison_widget import CharacterComparisonWidget, CharSnapshot
from pymon.ui.dark_theme import Colors
from pymon.ui.data_browser_widget import DataBrowserWidget
from pymon.ui.dockable_tab_widget import DockableTabWidget
from pymon.ui.implant_calculator_widget import ImplantCalculatorWidget
from pymon.ui.market_browser_widget import MarketBrowserWidget
from pymon.ui.owned_skill_books_widget import OwnedSkillBooksWidget
from pymon.ui.path_finder_widget import PathFinderWidget
from pymon.ui.schedule_editor_widget import ScheduleEditorWidget
from pymon.ui.ship_browser_widget import ShipBrowserWidget
from pymon.ui.sidebar_nav import SidebarNav, TabGroup
from pymon.ui.skill_planner_widget import SkillPlannerWidget
from pymon.ui.skills_pie_chart_widget import SkillsPieChartWidget
from pymon.ui.trade_advisor_widget import TradeAdvisorWidget
from pymon.ui.trade_tracker_widget import TradeTrackerWidget
from pymon.ui.wallet_chart_widget import WalletChartWidget
from pymon.ui.window_manager import WindowLayout, WindowManager

logger = logging.getLogger(__name__)


def _format_isk(value: float) -> str:
    """Format ISK with thousands separator."""
    return f"{value:,.2f} ISK"


def _format_sp(value: int) -> str:
    """Format skill points."""
    return f"{value:,}"


def _ts(dt: datetime | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """Format a datetime or return empty string."""
    return dt.strftime(fmt) if dt else ""


def _sec_color(sec: float) -> str:
    """CSS color for security status."""
    if sec >= 0.5:
        return "{Colors.ACCENT}"
    elif sec > 0.0:
        return "{Colors.ORANGE}"
    else:
        return "{Colors.RED}"


class MainWindow(QMainWindow):
    """PyMon main window."""

    # Signals for thread-safe UI updates (emitted from worker threads)
    sso_login_finished = Signal(object)
    sso_login_failed = Signal(str)
    _update_overview = Signal(str)
    _update_skill_queue = Signal(str)
    _update_skills = Signal(str)
    _update_server_status_text = Signal(str)
    _update_mail = Signal(str)
    _update_assets = Signal(str)
    _update_contracts = Signal(str)
    _update_industry = Signal(str)
    _update_fittings = Signal(str)
    _update_market = Signal(str)
    _update_killmails = Signal(str)
    _update_blueprints = Signal(str)
    _update_pi = Signal(str)
    _update_notifications = Signal(str)
    _update_contacts = Signal(str)
    _update_wallet = Signal(str)
    _update_calendar = Signal(str)
    _update_research = Signal(str)
    _update_medals = Signal(str)
    _update_clones = Signal(str)
    _update_bookmarks = Signal(str)
    _update_loyalty = Signal(str)
    _update_mining = Signal(str)
    _update_fw = Signal(str)
    _show_contract_detail = Signal(object, object)  # contract, items
    _update_portrait = Signal(QPixmap)
    _update_skill_planner = Signal(object, object, object)  # attributes, trained_skills, character_id
    _update_cert_browser = Signal(object, object)  # trained_skills, character_id
    _update_wallet_chart = Signal(object)  # journal entries
    _update_implant_calc = Signal(object, object)  # implant_ids, base_attributes
    _update_char_comparison = Signal(object)  # list[CharSnapshot]
    _update_skills_chart = Signal(object)  # list[SkillInfo]
    _update_skill_books = Signal(object, object, object)  # assets, trained_skills, loc_names
    _update_ship_browser = Signal(object)  # trained_skills dict
    _update_trade_tracker = Signal(object)  # wallet transactions list
    _update_trade_advisor_mining = Signal(object)  # mining ledger entries
    _update_trade_advisor_industry = Signal(object)  # industry products

    def __init__(self, config: Config, db: Database) -> None:
        super().__init__()
        self.config = config
        self.db = db
        self._really_quit = False
        self._shutting_down = False
        self._bg_threads: list = []  # track background threads

        # Connect signals
        self.sso_login_finished.connect(self._on_sso_login_finished)
        self.sso_login_failed.connect(self._on_sso_login_failed)

        # Initialize services
        self.esi = ESIClient()
        self.status_api = StatusAPI(self.esi)
        self.auth = EVEAuth(config.client_id, config.scopes)
        self.token_manager = TokenManager(db, self.auth)
        self.sde = SDEDatabase(config.sde_db_path)
        self.char_service = CharacterService(self.esi, self.token_manager, db, self.sde)
        self.name_resolver = NameResolver(self.esi, db, self.sde)

        # Current character ID
        self._current_character_id: int | None = None
        # Previous skill queue for completion detection
        self._prev_skill_queue: list | None = None

        # Setup UI
        self._setup_ui()
        self._setup_menu()
        self._setup_status_bar()
        self._setup_tray_icon()

        # Connect label-update signals
        self._update_overview.connect(lambda html: self.overview_label.setText(html))
        self._update_skill_queue.connect(lambda html: self.skill_queue_label.setText(html))
        self._update_skills.connect(lambda html: self.skills_label.setText(html))
        self._update_server_status_text.connect(lambda text: self.server_status_label.setText(text))
        self._update_mail.connect(lambda html: self.mail_label.setText(html))
        self._update_assets.connect(lambda html: self.assets_label.setText(html))
        self._update_contracts.connect(lambda html: self.contracts_label.setText(html))
        self._contracts_cache: list = []  # cached for detail popup
        self._show_contract_detail.connect(self._display_contract_detail)
        self._update_industry.connect(lambda html: self.industry_label.setText(html))
        self._update_fittings.connect(lambda html: self.fittings_label.setText(html))
        self._update_market.connect(lambda html: self.market_label.setText(html))
        self._update_killmails.connect(lambda html: self.killmails_label.setText(html))
        self._update_blueprints.connect(lambda html: self.blueprints_label.setText(html))
        self._update_pi.connect(lambda html: self.pi_label.setText(html))
        self._update_notifications.connect(lambda html: self.notifications_label.setText(html))
        self._update_contacts.connect(lambda html: self.contacts_label.setText(html))
        self._update_wallet.connect(lambda html: self.wallet_label.setText(html))
        self._update_calendar.connect(lambda html: self.calendar_label.setText(html))
        self._update_research.connect(lambda html: self.research_label.setText(html))
        self._update_medals.connect(lambda html: self.medals_label.setText(html))
        self._update_clones.connect(lambda html: self.clones_label.setText(html))
        self._update_bookmarks.connect(lambda html: self.bookmarks_label.setText(html))
        self._update_loyalty.connect(lambda html: self.loyalty_label.setText(html))
        self._update_mining.connect(lambda html: self.mining_label.setText(html))
        self._update_fw.connect(lambda html: self.fw_label.setText(html))
        self._update_portrait.connect(self._on_portrait_loaded)
        self._update_skill_planner.connect(
            lambda attrs, skills, cid: self.skill_planner.set_character_data(attrs, skills, cid)
        )
        self._update_cert_browser.connect(
            lambda skills, cid: self.cert_browser.set_character_data(skills, cid)
        )
        self._update_wallet_chart.connect(
            lambda journal: self.wallet_chart.set_journal_data(journal)
        )
        self._update_implant_calc.connect(
            lambda imp_ids, attrs: self.implant_calc.set_data(imp_ids, attrs)
        )
        self._update_char_comparison.connect(
            lambda snaps: self.char_comparison.set_data(snaps)
        )
        self._update_skills_chart.connect(
            lambda skills: self.skills_chart.set_skills_data(skills)
        )
        self._update_skill_books.connect(
            lambda assets, trained, locs: self.skill_books.set_data(assets, trained, locs)
        )
        self._update_ship_browser.connect(
            lambda trained: self.ship_browser.set_trained_skills(trained)
        )
        self._update_trade_tracker.connect(
            lambda txns: self.trade_tracker.update_transactions(txns)
        )
        self._update_trade_advisor_mining.connect(
            lambda ledger: self.trade_advisor.set_mining_ledger(ledger)
        )
        self._update_trade_advisor_industry.connect(
            lambda products: self.trade_advisor.set_industry_products(products)
        )

        # Auto-refresh timer
        self._refresh_timer = QTimer()
        self._refresh_timer.setInterval(self.config.refresh_interval_minutes * 60_000)
        self._refresh_timer.timeout.connect(self.refresh_data)
        self._refresh_timer.start()

        # Skill queue countdown timer (updates title every 30s)
        self._countdown_timer = QTimer()
        self._countdown_timer.setInterval(30_000)
        self._countdown_timer.timeout.connect(self._update_training_countdown)
        self._countdown_timer.start()
        self._training_finish: datetime | None = None
        self._training_skill_name: str = ""
        self._training_level: int = 0

        # Email notifier
        self._email_notifier = EmailNotifier(
            smtp_server=self.config.email_smtp_server,
            smtp_port=self.config.email_smtp_port,
            smtp_user=self.config.email_smtp_user,
            smtp_password=self.config.email_smtp_password,
            email_to=self.config.email_to,
            use_tls=self.config.email_use_tls,
        )

        # Cloud sync
        self._cloud_sync = CloudSync(
            sync_folder=self.config.cloud_sync_path,
            data_dir=str(self.config.data_dir),
        )

        # Load characters
        self._load_characters()

        # Window layout manager (multi-monitor persistence)
        self._window_manager = WindowManager(self.config.data_dir)
        self._restore_window_layout()

        # Auto-update check (after UI is ready)
        if self.config.auto_update_check:
            QTimer.singleShot(2000, self._check_for_updates)

    # ══════════════════════════════════════════════════════════════════
    #  UI SETUP
    # ══════════════════════════════════════════════════════════════════

    def _setup_ui(self) -> None:
        """Initialize the UI layout."""
        self.setWindowTitle("PyMon – EVE Online Character Monitor")
        self.setMinimumSize(1000, 700)
        self.resize(1400, 900)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left panel: Portrait + char list + sidebar nav ──
        left_widget = QWidget()
        left_widget.setProperty("cssClass", "sidebar")
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(8)

        # Portrait
        self.portrait_label = QLabel()
        self.portrait_label.setFixedSize(140, 140)
        self.portrait_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.portrait_label.setProperty("cssClass", "card")
        self.portrait_label.setText("No Character")
        left_layout.addWidget(self.portrait_label, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Character list
        self.char_list = QListWidget()
        self.char_list.setMaximumHeight(150)
        self.char_list.setMinimumWidth(180)
        self.char_list.setMaximumWidth(220)
        self.char_list.setFont(QFont("Segoe UI", 11))
        self.char_list.currentRowChanged.connect(self._on_character_selected)
        left_layout.addWidget(self.char_list)

        # ── Sidebar navigation (grouped tabs) ──
        self._tab_groups_def = [
            TabGroup("character", "Charakter", "👤", [
                "Übersicht", "Klone", "Kontakte", "Medaillen",
                "Lesezeichen", "Kalender", "LP", "FW Stats",
            ]),
            TabGroup("skills", "Skills", "📊", [
                "Skill Queue", "Skills", "Skill Planner",
                "Zertifikate", "Wochenplaner",
            ]),
            TabGroup("finance", "Finanzen", "💰", [
                "Wallet", "Markt", "Marktbrowser", "Trade Tracker",
                "Handelsberater", "Contracts", "Mining", "ISK Chart",
            ]),
            TabGroup("industry", "Industrie", "🏭", [
                "Industrie", "Blueprints", "Fittings",
                "Assets", "Research",
            ]),
            TabGroup("combat", "Kampf & Sozial", "⚔️", [
                "Killmails", "Mail", "Benachrichtigungen",
                "PI",
            ]),
            TabGroup("tools", "Tools & Analyse", "🔧", [
                "Implant Calc", "Char-Vergleich", "SP Chart",
                "Skill Books", "Datenbrowser", "API Tester",
                "Ship Browser", "Path Finder",
            ]),
        ]

        self.sidebar_nav = SidebarNav(self._tab_groups_def)
        self.sidebar_nav.tab_selected.connect(self._on_sidebar_tab_selected)
        self.sidebar_nav.tab_popout_requested.connect(self._on_sidebar_tab_popout)
        self.sidebar_nav.group_popout_requested.connect(self._on_sidebar_group_popout)
        left_layout.addWidget(self.sidebar_nav, 1)  # stretch=1 to fill remaining space

        splitter.addWidget(left_widget)

        # ── Right: Dockable tab widget (with hidden tab bar) ──
        self.tabs = DockableTabWidget()
        self.tabs.setTabPosition(QTabWidget.TabPosition.North)
        # Hide the tab bar – navigation is done via sidebar
        self.tabs.tabBar().setVisible(False)

        def _make_tab(placeholder: str, tab_title: str) -> QLabel:
            """Create a scrollable tab with a QLabel."""
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            label = QLabel(placeholder)
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            label.setContentsMargins(12, 12, 12, 12)
            label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.LinksAccessibleByMouse
            )
            scroll.setWidget(label)
            self.tabs.addTab(scroll, tab_title)
            return label

        # ── Create all label-based tabs ──
        self.overview_label = _make_tab("Wähle einen Charakter oder füge einen neuen hinzu.", "Übersicht")
        self.skill_queue_label = _make_tab("Skill Queue wird geladen...", "Skill Queue")
        self.skills_label = _make_tab("Skills werden geladen...", "Skills")
        self.mail_label = _make_tab("", "Mail")
        self.wallet_label = _make_tab("", "Wallet")
        self.assets_label = _make_tab("", "Assets")
        self.contracts_label = _make_tab("", "Contracts")
        self.contracts_label.linkActivated.connect(self._on_contract_link)
        self.industry_label = _make_tab("", "Industrie")
        self.market_label = _make_tab("", "Markt")
        self.fittings_label = _make_tab("", "Fittings")
        self.blueprints_label = _make_tab("", "Blueprints")
        self.killmails_label = _make_tab("", "Killmails")
        self.pi_label = _make_tab("", "PI")
        self.contacts_label = _make_tab("", "Kontakte")
        self.notifications_label = _make_tab("", "Benachrichtigungen")
        self.calendar_label = _make_tab("", "Kalender")
        self.research_label = _make_tab("", "Research")
        self.medals_label = _make_tab("", "Medaillen")
        self.clones_label = _make_tab("", "Klone")
        self.bookmarks_label = _make_tab("", "Lesezeichen")
        self.loyalty_label = _make_tab("", "LP")
        self.mining_label = _make_tab("", "Mining")
        self.fw_label = _make_tab("", "FW Stats")

        # ── Widget-based tabs (with group assignments) ──
        self.skill_planner = SkillPlannerWidget(self.sde, db=self.db)
        self.tabs.add_tab_to_group(self.skill_planner, "Skill Planner", "skills")

        self.cert_browser = CertificateBrowserWidget(self.sde)
        self.tabs.add_tab_to_group(self.cert_browser, "Zertifikate", "skills")

        self.schedule_editor = ScheduleEditorWidget(db=self.db)
        self.tabs.add_tab_to_group(self.schedule_editor, "Wochenplaner", "skills")

        self.wallet_chart = WalletChartWidget()
        self.tabs.add_tab_to_group(self.wallet_chart, "ISK Chart", "finance")

        self.market_browser = MarketBrowserWidget(self.esi, self.sde)
        self.tabs.add_tab_to_group(self.market_browser, "Marktbrowser", "finance")

        self.trade_tracker = TradeTrackerWidget(self.esi, self.sde)
        self.tabs.add_tab_to_group(self.trade_tracker, "Trade Tracker", "finance")

        self.trade_advisor = TradeAdvisorWidget(self.esi, self.sde)
        self.tabs.add_tab_to_group(self.trade_advisor, "Handelsberater", "finance")

        self.implant_calc = ImplantCalculatorWidget(self.sde)
        self.tabs.add_tab_to_group(self.implant_calc, "Implant Calc", "tools")

        self.char_comparison = CharacterComparisonWidget()
        self.tabs.add_tab_to_group(self.char_comparison, "Char-Vergleich", "tools")

        self.skills_chart = SkillsPieChartWidget()
        self.tabs.add_tab_to_group(self.skills_chart, "SP Chart", "tools")

        self.skill_books = OwnedSkillBooksWidget(self.sde)
        self.tabs.add_tab_to_group(self.skill_books, "Skill Books", "tools")

        self.data_browser = DataBrowserWidget(self.sde)
        self.tabs.add_tab_to_group(self.data_browser, "Datenbrowser", "tools")

        self.api_tester = APITesterWidget(self.esi, self.token_manager)
        self.tabs.add_tab_to_group(self.api_tester, "API Tester", "tools")

        self.ship_browser = ShipBrowserWidget(self.sde)
        self.tabs.add_tab_to_group(self.ship_browser, "Ship Browser", "tools")

        self.path_finder = PathFinderWidget(self.sde)
        self.tabs.add_tab_to_group(self.path_finder, "Path Finder", "tools")

        # Register label-based tabs in their groups too
        _label_tab_groups = {
            "character": ["Übersicht", "Klone", "Kontakte", "Medaillen",
                          "Lesezeichen", "Kalender", "LP", "FW Stats"],
            "skills":    ["Skill Queue", "Skills"],
            "finance":   ["Wallet", "Markt", "Contracts", "Mining"],
            "industry":  ["Industrie", "Blueprints", "Fittings", "Assets", "Research"],
            "combat":    ["Killmails", "Mail", "Benachrichtigungen", "PI"],
        }
        for group_key, tab_names in _label_tab_groups.items():
            for name in tab_names:
                if group_key not in self.tabs._tab_groups:
                    self.tabs._tab_groups[group_key] = []
                if name not in self.tabs._tab_groups[group_key]:
                    self.tabs._tab_groups[group_key].append(name)

        # Sync sidebar + tab widget: when tab changes, update sidebar
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.tabs.tab_detached.connect(self._on_tab_detached_from_bar)
        self.tabs.tab_docked.connect(self._on_tab_docked_from_bar)
        self.tabs.group_docked.connect(self._on_group_docked)

        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        self.setCentralWidget(splitter)

        # Default: select first tab and highlight in sidebar
        self.sidebar_nav.set_active_tab("Übersicht")

    # ── Sidebar ↔ TabWidget synchronisation ──────────────────────

    def _on_sidebar_tab_selected(self, tab_name: str) -> None:
        """User clicked a tab entry in the sidebar → switch the tab widget."""
        self.tabs.select_tab_by_title(tab_name)

    def _on_sidebar_tab_popout(self, tab_name: str) -> None:
        """User requested to detach a single tab from the sidebar context menu."""
        self.tabs.detach_tab_by_title(tab_name)

    def _on_sidebar_group_popout(self, group_key: str) -> None:
        """User requested to detach all tabs of a group."""
        self.tabs.detach_group(group_key)

    def _on_tab_changed(self, index: int) -> None:
        """Tab widget's current tab changed → sync sidebar highlight."""
        if index >= 0:
            title = self.tabs.tabText(index)
            self.sidebar_nav.set_active_tab(title)

    def _on_tab_detached_from_bar(self, title: str) -> None:
        """A single tab was detached → grey it out or remove from sidebar."""
        self.sidebar_nav.remove_tab(title)

    def _on_tab_docked_from_bar(self, title: str) -> None:
        """A single tab was re-docked → re-add to sidebar."""
        group_key = self.sidebar_nav.find_group_for_tab(title)
        if group_key:
            self.sidebar_nav.add_tab(title, group_key)
        # Select the re-docked tab
        self.sidebar_nav.set_active_tab(title)

    def _on_group_docked(self, group_key: str) -> None:
        """An entire group was re-docked → re-add all tabs to sidebar."""
        tab_names = self.tabs._tab_groups.get(group_key, [])
        for name in tab_names:
            if not self.sidebar_nav.has_tab(name):
                self.sidebar_nav.add_tab(name, group_key)

    def _setup_menu(self) -> None:
        """Setup the menu bar."""
        menu_bar = self.menuBar()

        # File menu
        file_menu = menu_bar.addMenu("&Datei")

        add_char_action = QAction("Charakter &hinzufügen (SSO Login)...", self)
        add_char_action.triggered.connect(self._on_add_character)
        file_menu.addAction(add_char_action)

        remove_char_action = QAction("Charakter &entfernen", self)
        remove_char_action.triggered.connect(self._on_remove_character)
        file_menu.addAction(remove_char_action)

        blank_char_action = QAction("&Blank Character erstellen...", self)
        blank_char_action.triggered.connect(self._on_create_blank_character)
        file_menu.addAction(blank_char_action)

        file_menu.addSeparator()

        refresh_action = QAction("Daten &aktualisieren", self)
        refresh_action.triggered.connect(self.refresh_data)
        file_menu.addAction(refresh_action)

        file_menu.addSeparator()

        import_sde_action = QAction("SDE-Daten &importieren...", self)
        import_sde_action.triggered.connect(self._on_import_sde)
        file_menu.addAction(import_sde_action)

        update_sde_action = QAction("SDE Online a&ktualisieren", self)
        update_sde_action.triggered.connect(self._on_update_sde_online)
        file_menu.addAction(update_sde_action)

        file_menu.addSeparator()

        settings_action = QAction("&Einstellungen...", self)
        settings_action.triggered.connect(self._on_settings)
        file_menu.addAction(settings_action)

        file_menu.addSeparator()

        export_csv_action = QAction("Tab als &CSV exportieren...", self)
        export_csv_action.triggered.connect(self._on_export_csv)
        file_menu.addAction(export_csv_action)

        export_ics_action = QAction("Skill Queue als &ICS exportieren...", self)
        export_ics_action.triggered.connect(self._on_export_ics)
        file_menu.addAction(export_ics_action)

        file_menu.addSeparator()

        cloud_export_action = QAction("☁️ Cloud-Backup exportieren...", self)
        cloud_export_action.triggered.connect(self._on_cloud_export)
        file_menu.addAction(cloud_export_action)

        cloud_import_action = QAction("☁️ Cloud-Backup importieren...", self)
        cloud_import_action.triggered.connect(self._on_cloud_import)
        file_menu.addAction(cloud_import_action)

        file_menu.addSeparator()

        exit_action = QAction("&Beenden", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Help menu
        help_menu = menu_bar.addMenu("&Hilfe")

        setup_wizard_action = QAction("🔧 &Einrichtungsassistent...", self)
        setup_wizard_action.triggered.connect(self._on_setup_wizard)
        help_menu.addAction(setup_wizard_action)

        help_menu.addSeparator()

        about_action = QAction("Über &PyMon", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)

    def _setup_status_bar(self) -> None:
        """Setup the status bar with server status and EVE time."""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.server_status_label = QLabel("Server-Status: Wird abgefragt...")
        self.status_bar.addPermanentWidget(self.server_status_label)

        self.eve_time_label = QLabel("")
        self.status_bar.addPermanentWidget(self.eve_time_label)

        # EVE time update timer (every second)
        self._eve_time_timer = QTimer()
        self._eve_time_timer.setInterval(1000)
        self._eve_time_timer.timeout.connect(self._update_eve_time)
        self._eve_time_timer.start()

        # Initial server status fetch
        QTimer.singleShot(500, self._update_server_status)

    def _setup_tray_icon(self) -> None:
        """Setup system tray icon."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._tray_icon = None
            return

        self._tray_icon = QSystemTrayIcon(self)
        # Use a simple colored pixmap as icon
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        from PySide6.QtGui import QBrush, QColor, QPainter
        painter = QPainter(pixmap)
        painter.setBrush(QBrush(QColor("{Colors.ACCENT}")))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(2, 2, 28, 28)
        painter.end()
        icon = QIcon(pixmap)

        self._tray_icon.setIcon(icon)
        self.setWindowIcon(icon)
        self._tray_icon.setToolTip("PyMon – EVE Character Monitor")

        # Tray menu
        tray_menu = QMenu()
        show_action = tray_menu.addAction("Anzeigen")
        show_action.triggered.connect(self._on_tray_show)
        tray_menu.addSeparator()
        quit_action = tray_menu.addAction("Beenden")
        quit_action.triggered.connect(self._on_tray_quit)
        self._tray_icon.setContextMenu(tray_menu)
        self._tray_icon.activated.connect(self._on_tray_activated)
        self._tray_icon.show()

    # ══════════════════════════════════════════════════════════════════
    #  EVE TIME
    # ══════════════════════════════════════════════════════════════════

    def _update_eve_time(self) -> None:
        """Update EVE time display in status bar (UTC)."""
        now = datetime.now(UTC)
        self.eve_time_label.setText(f"EVE: {now.strftime('%H:%M:%S')}")

    # ══════════════════════════════════════════════════════════════════
    #  SYSTEM TRAY
    # ══════════════════════════════════════════════════════════════════

    def _on_tray_show(self) -> None:
        self.showNormal()
        self.activateWindow()

    def _on_tray_quit(self) -> None:
        self._really_quit = True
        self.close()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._on_tray_show()

    def changeEvent(self, event) -> None:
        """Minimize to tray."""
        from PySide6.QtCore import QEvent
        if (
            event.type() == QEvent.Type.WindowStateChange
            and self.isMinimized()
            and self._tray_icon
        ):
            self.hide()
            self._tray_icon.showMessage(
                "PyMon",
                "PyMon läuft im Hintergrund weiter.",
                QSystemTrayIcon.MessageIcon.Information,
                2000,
            )
            event.ignore()
        else:
            super().changeEvent(event)

    # ══════════════════════════════════════════════════════════════════
    #  CHARACTER LIST
    # ══════════════════════════════════════════════════════════════════

    def _load_characters(self) -> None:
        """Load saved characters into the list."""
        self.char_list.clear()
        characters = self.token_manager.get_all_characters()
        for char in characters:
            item = QListWidgetItem(char["character_name"])
            item.setData(Qt.ItemDataRole.UserRole, char["character_id"])
            self.char_list.addItem(item)
        # Auto-select first character if only one exists
        if self.char_list.count() == 1:
            self.char_list.setCurrentRow(0)

    def _on_character_selected(self, row: int) -> None:
        """Handle character selection."""
        if row < 0:
            return
        item = self.char_list.item(row)
        if not item:
            return
        character_id = item.data(Qt.ItemDataRole.UserRole)
        self._current_character_id = character_id
        self.api_tester.set_character_id(character_id)
        self.schedule_editor.set_character_id(character_id)
        self._fetch_character_data(character_id)

    # ══════════════════════════════════════════════════════════════════
    #  SSO LOGIN
    # ══════════════════════════════════════════════════════════════════

    def _on_add_character(self) -> None:
        """Start SSO login flow to add a character."""
        if not self.config.client_id:
            QMessageBox.warning(
                self,
                "Client-ID fehlt",
                "Bitte konfiguriere zuerst deine EVE Application Client-ID.\n\n"
                "Registriere eine App unter:\nhttps://developers.eveonline.com/applications\n\n"
                "Setze die Client-ID in der config.json.",
            )
            return
        self.status_bar.showMessage("SSO Login: Öffne Browser...")
        self.auth.open_browser_login()
        self._wait_for_sso_callback()

    def _wait_for_sso_callback(self) -> None:
        """Wait for SSO callback asynchronously."""
        import threading

        def _run_callback_server() -> None:
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                server = CallbackServer()
                logger.info("Waiting for SSO callback on port 8182...")
                callback_result = loop.run_until_complete(server.wait_for_callback())
                logger.info("SSO callback received, exchanging code...")
                sso_result = loop.run_until_complete(
                    self.auth.exchange_code(callback_result.code, callback_result.state)
                )
                logger.info("SSO login successful for %s", sso_result.character_name)
                self.sso_login_finished.emit(sso_result)
            except Exception as e:
                logger.error("SSO login failed", exc_info=True)
                self.sso_login_failed.emit(str(e))

        thread = threading.Thread(target=_run_callback_server, daemon=True)
        thread.start()

    def _on_sso_login_finished(self, sso_result: object) -> None:
        """Handle successful SSO login on the main thread."""
        try:
            self.token_manager.store_tokens(sso_result)
            self._load_characters()
            # Auto-select the newly added character
            for i in range(self.char_list.count()):
                item = self.char_list.item(i)
                if item and item.data(Qt.ItemDataRole.UserRole) == sso_result.character_id:
                    self.char_list.setCurrentRow(i)
                    break
            self.status_bar.showMessage(f"✓ {sso_result.character_name} hinzugefügt!")
        except Exception as e:
            logger.error("Failed to store SSO tokens", exc_info=True)
            self.status_bar.showMessage(f"✗ Fehler beim Speichern: {e}")

    def _on_sso_login_failed(self, error_msg: str) -> None:
        """Handle failed SSO login on the main thread."""
        self.status_bar.showMessage(f"✗ SSO Login fehlgeschlagen: {error_msg}")

    def _on_remove_character(self) -> None:
        """Remove the selected character."""
        item = self.char_list.currentItem()
        if not item:
            return
        character_id = item.data(Qt.ItemDataRole.UserRole)
        name = item.text()
        reply = QMessageBox.question(
            self,
            "Charakter entfernen",
            f"Möchtest du '{name}' wirklich entfernen?",
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.token_manager.remove_character(character_id)
            self._load_characters()

    def _on_create_blank_character(self) -> None:
        """Create a virtual blank character for plan simulation."""
        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(
            self,
            "Blank Character",
            "Name für den virtuellen Charakter:",
            text="Blank Character",
        )
        if not ok or not name.strip():
            return

        name = name.strip()

        # Generate a unique negative ID to distinguish from real characters
        import random
        blank_id = -(random.randint(100_000, 999_999))

        # Insert into DB with no tokens
        try:
            self.db.conn.execute(
                """INSERT OR REPLACE INTO characters
                   (character_id, character_name, corporation_id, alliance_id,
                    access_token, refresh_token, token_expiry, scopes)
                   VALUES (?, ?, NULL, NULL, NULL, NULL, NULL, '')""",
                (blank_id, name),
            )
            self.db.conn.commit()
        except Exception as e:
            QMessageBox.critical(self, "Fehler", f"Konnte Charakter nicht anlegen:\n{e}")
            return

        self._load_characters()

        # Select the new blank character
        for i in range(self.char_list.count()):
            item = self.char_list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == blank_id:
                self.char_list.setCurrentRow(i)
                break

        # Set blank data directly (all skills 0, default attributes)
        attrs = {
            "intelligence": 17, "memory": 17,
            "perception": 17, "willpower": 17, "charisma": 17,
        }
        self.skill_planner.set_character_data(attrs, {}, blank_id)
        self.overview_label.setText(
            f"<h2>🧪 {name}</h2>"
            "<p>Virtueller Charakter für Skill-Plan-Simulation.</p>"
            "<p>Alle Skills auf Level 0 — nutze den Skill Planner, um Pläne zu erstellen.</p>"
            "<table><tr><th>Attribut</th><th>Wert</th></tr>"
            "<tr><td>Intelligence</td><td>17</td></tr>"
            "<tr><td>Memory</td><td>17</td></tr>"
            "<tr><td>Perception</td><td>17</td></tr>"
            "<tr><td>Willpower</td><td>17</td></tr>"
            "<tr><td>Charisma</td><td>17</td></tr>"
            "</table>"
        )
        self.status_bar.showMessage(f"✓ Blank Character '{name}' erstellt (ID: {blank_id})")

    # ══════════════════════════════════════════════════════════════════
    #  SDE IMPORT
    # ══════════════════════════════════════════════════════════════════

    def _on_import_sde(self) -> None:
        """Import SDE data."""
        from PySide6.QtWidgets import QFileDialog
        sde_dir = QFileDialog.getExistingDirectory(self, "SDE JSONL Verzeichnis auswählen")
        if not sde_dir:
            return
        try:
            self.status_bar.showMessage("SDE-Import läuft...")
            from pymon.sde.loader import import_sde
            import_sde(sde_dir, self.config.sde_db_path)
            self.sde = SDEDatabase(self.config.sde_db_path)
            self.char_service.sde = self.sde
            self.name_resolver.sde = self.sde
            build = self.sde.get_build_number()
            self.status_bar.showMessage(f"✓ SDE importiert (Build {build})")
        except Exception as e:
            self.status_bar.showMessage(f"✗ SDE-Import Fehler: {e}")

    def _on_update_sde_online(self) -> None:
        """Download latest SDE from data.everef.net and import it."""
        current_build = self.sde.get_build_number() if self.sde else None

        # Create progress dialog and download thread
        dialog = SDEUpdateDialog.create(self)
        thread = SDEDownloadThread(
            db_path=self.config.sde_db_path,
            current_build=current_build,
            parent=self,
        )

        # Connect signals
        thread.progress.connect(dialog.on_progress)
        thread.status.connect(dialog.on_status)
        thread.finished_ok.connect(dialog.on_finished_ok)
        thread.finished_err.connect(dialog.on_finished_err)
        dialog.cancel_requested.connect(thread.cancel)

        def _on_done(build: int) -> None:
            self.sde = SDEDatabase(self.config.sde_db_path)
            self.char_service.sde = self.sde
            self.name_resolver.sde = self.sde
            self.status_bar.showMessage(
                f"✓ SDE online aktualisiert (Build {build})"
            )

        thread.finished_ok.connect(_on_done)

        # Store reference to prevent GC
        self._sde_update_thread = thread

        thread.start()
        dialog.exec()

    # ══════════════════════════════════════════════════════════════════
    #  SETTINGS
    # ══════════════════════════════════════════════════════════════════

    def _on_settings(self) -> None:
        """Open settings dialog."""
        from pymon.ui.settings_dialog import SettingsDialog
        dialog = SettingsDialog(self.config, self)
        if dialog.exec():
            self.config.save()
            # Re-initialize auth with new client_id
            self.auth = EVEAuth(self.config.client_id, self.config.scopes)
            self.token_manager.auth = self.auth
            # Update email notifier
            self._email_notifier.update_settings(
                smtp_server=self.config.email_smtp_server,
                smtp_port=self.config.email_smtp_port,
                smtp_user=self.config.email_smtp_user,
                smtp_password=self.config.email_smtp_password,
                email_to=self.config.email_to,
                use_tls=self.config.email_use_tls,
            )
            # Update cloud sync
            self._cloud_sync.update_settings(
                sync_folder=self.config.cloud_sync_path,
                data_dir=str(self.config.data_dir),
            )
            self.status_bar.showMessage("✓ Einstellungen gespeichert")

    # ══════════════════════════════════════════════════════════════════
    #  DATA FETCHING – MAIN DISPATCHER
    # ══════════════════════════════════════════════════════════════════

    def _fetch_character_data(self, character_id: int) -> None:
        """Fetch and display character data."""
        import threading

        logger.info("Starting data fetch for character %d", character_id)

        # Show loading state on all tabs
        self.overview_label.setText("<p>Lade Charakterdaten...</p>")
        self.skill_queue_label.setText("<p>Lade Skill Queue...</p>")
        self.skills_label.setText("<p>Lade Skills...</p>")
        self.mail_label.setText("<p>Lade Mail...</p>")
        self.wallet_label.setText("<p>Lade Wallet...</p>")
        self.assets_label.setText("<p>Lade Assets...</p>")
        self.contracts_label.setText("<p>Lade Contracts...</p>")
        self.industry_label.setText("<p>Lade Industrie-Jobs...</p>")
        self.market_label.setText("<p>Lade Markt-Orders...</p>")
        self.fittings_label.setText("<p>Lade Fittings...</p>")
        self.blueprints_label.setText("<p>Lade Blueprints...</p>")
        self.killmails_label.setText("<p>Lade Killmails...</p>")
        self.pi_label.setText("<p>Lade PI-Kolonien...</p>")
        self.contacts_label.setText("<p>Lade Kontakte...</p>")
        self.notifications_label.setText("<p>Lade Benachrichtigungen...</p>")
        self.calendar_label.setText("<p>Lade Kalender...</p>")
        self.research_label.setText("<p>Lade Research...</p>")
        self.medals_label.setText("<p>Lade Medaillen...</p>")
        self.clones_label.setText("<p>Lade Klone...</p>")
        self.bookmarks_label.setText("<p>Lade Lesezeichen-Status...</p>")
        self.loyalty_label.setText("<p>Lade LP...</p>")
        self.mining_label.setText("<p>Lade Mining...</p>")
        self.fw_label.setText("<p>Lade FW Stats...</p>")

        def _fetch() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                fetchers = [
                    self._fetch_overview_tab,
                    self._fetch_skill_queue_tab,
                    self._fetch_skills_tab,
                    self._fetch_mail_tab,
                    self._fetch_wallet_tab,
                    self._fetch_assets_tab,
                    self._fetch_contracts_tab,
                    self._fetch_industry_tab,
                    self._fetch_market_tab,
                    self._fetch_fittings_tab,
                    self._fetch_blueprints_tab,
                    self._fetch_killmails_tab,
                    self._fetch_pi_tab,
                    self._fetch_contacts_tab,
                    self._fetch_notifications_tab,
                    self._fetch_calendar_tab,
                    self._fetch_research_tab,
                    self._fetch_medals_tab,
                    self._fetch_clones_tab,
                    self._fetch_bookmarks_tab,
                    self._fetch_loyalty_tab,
                    self._fetch_mining_tab,
                    self._fetch_fw_tab,
                    self._fetch_portrait,
                    self._fetch_char_comparison,
                ]
                for fetcher in fetchers:
                    if self._shutting_down:
                        logger.info("Shutdown requested, aborting fetch")
                        return
                    try:
                        fetcher(loop, character_id)
                    except Exception:
                        if self._shutting_down:
                            return
                        logger.error("Error in %s", fetcher.__name__, exc_info=True)
            finally:
                loop.close()

        # Clean up finished threads
        self._bg_threads = [t for t in self._bg_threads if t.is_alive()]
        thread = threading.Thread(target=_fetch, daemon=True, name="pymon-fetch")
        self._bg_threads.append(thread)
        thread.start()

    # ══════════════════════════════════════════════════════════════════
    #  CHARACTER COMPARISON – data for all characters
    # ══════════════════════════════════════════════════════════════════

    def _fetch_char_comparison(self, loop: asyncio.AbstractEventLoop, _cid: int) -> None:
        """Fetch overview + skills for every registered character and emit comparison."""
        try:
            all_chars = self.token_manager.get_all_characters()
            if len(all_chars) < 1:
                return

            snapshots: list[CharSnapshot] = []
            for ch in all_chars:
                char_id = ch["character_id"]
                try:
                    char = loop.run_until_complete(
                        self.char_service.fetch_character_overview(char_id)
                    )
                    if not char:
                        continue

                    # Resolve corp/alliance
                    resolve_ids = [char.corporation_id]
                    if char.alliance_id:
                        resolve_ids.append(char.alliance_id)
                    names = loop.run_until_complete(
                        self.name_resolver.resolve_many(resolve_ids)
                    )
                    corp_name = names.get(char.corporation_id, "")
                    alliance_name = names.get(char.alliance_id, "") if char.alliance_id else ""

                    # Skills summary
                    skills = loop.run_until_complete(
                        self.char_service.fetch_skills(char_id)
                    )
                    skill_count = len(skills)
                    skills_at_5 = sum(1 for s in skills if s.active_skill_level == 5)

                    # Skill queue
                    queue = loop.run_until_complete(
                        self.char_service.fetch_skill_queue(char_id)
                    )
                    queue_finish = ""
                    current_training = ""
                    if queue:
                        last = max(queue, key=lambda e: e.queue_position)
                        if last.finish_date:
                            queue_finish = last.finish_date.strftime("%Y-%m-%d %H:%M")
                        training = [e for e in queue if e.is_training]
                        if training:
                            current_training = f"{training[0].skill_name} → L{training[0].finished_level}"

                    # Attributes
                    attrs = loop.run_until_complete(
                        self.char_service.fetch_attributes(char_id)
                    )

                    snap = CharSnapshot(
                        character_id=char_id,
                        character_name=char.character_name,
                        corporation_name=corp_name,
                        alliance_name=alliance_name,
                        total_sp=char.total_sp,
                        unallocated_sp=char.unallocated_sp,
                        wallet_balance=char.wallet_balance,
                        security_status=char.security_status,
                        intelligence=attrs.get("intelligence", 17),
                        memory=attrs.get("memory", 17),
                        perception=attrs.get("perception", 17),
                        willpower=attrs.get("willpower", 17),
                        charisma=attrs.get("charisma", 17),
                        skill_count=skill_count,
                        skills_at_5=skills_at_5,
                        queue_length=len(queue),
                        queue_finish=queue_finish,
                        current_training=current_training,
                        birthday=char.birthday,
                    )
                    snapshots.append(snap)
                except Exception:
                    logger.debug("Comparison: skip char %d", char_id, exc_info=True)

            if snapshots:
                self._update_char_comparison.emit(snapshots)
        except Exception:
            logger.error("Character comparison error", exc_info=True)

    # ══════════════════════════════════════════════════════════════════
    #  OVERVIEW TAB – Character Info + Corp/Alliance Names
    # ══════════════════════════════════════════════════════════════════

    def _fetch_overview_tab(self, loop: asyncio.AbstractEventLoop, cid: int) -> None:
        try:
            char = loop.run_until_complete(self.char_service.fetch_character_overview(cid))
            if not char:
                self._update_overview.emit("<p style='color:red'>Fehler beim Laden</p>")
                return

            # Resolve corp/alliance names
            ids_to_resolve = [char.corporation_id]
            if char.alliance_id:
                ids_to_resolve.append(char.alliance_id)
            names = loop.run_until_complete(self.name_resolver.resolve_many(ids_to_resolve))
            corp_name = names.get(char.corporation_id, f"#{char.corporation_id}")
            alliance_name = names.get(char.alliance_id, "") if char.alliance_id else ""

            # Fetch attributes
            attrs = loop.run_until_complete(self.char_service.fetch_attributes(cid))

            # Fetch employment history
            history = loop.run_until_complete(self.char_service.fetch_employment_history(cid))
            # Resolve corporation IDs in history
            hist_corp_ids = [h.get("corporation_id", 0) for h in history if h.get("corporation_id")]
            if hist_corp_ids:
                hist_names = loop.run_until_complete(self.name_resolver.resolve_many(hist_corp_ids))
            else:
                hist_names = {}

            # Security status color
            sec = char.security_status
            sec_col = _sec_color(sec)

            # Online indicator
            online_icon = "🟢" if char.is_online else "🔴"

            html = f"""
            <h2>{char.character_name} {online_icon}</h2>
            <table cellspacing='6'>
              <tr><td><b>Corporation:</b></td><td>{corp_name}</td></tr>
              {'<tr><td><b>Alliance:</b></td><td>' + alliance_name + '</td></tr>' if alliance_name else ''}
              <tr><td><b>Sicherheitsstatus:</b></td><td style='color:{sec_col}'>{sec:+.2f}</td></tr>
              <tr><td><b>Geburtstag:</b></td><td>{char.birthday[:10]}</td></tr>
              <tr><td><b>Standort:</b></td><td>{char.solar_system_name}</td></tr>
              <tr><td><b>Schiff:</b></td><td>{char.ship_name}</td></tr>
              <tr><td><b>Wallet:</b></td><td style='color:{Colors.ACCENT}'>{_format_isk(char.wallet_balance)}</td></tr>
              <tr><td><b>Total SP:</b></td><td>{_format_sp(char.total_sp)}</td></tr>
              <tr><td><b>Unallocated SP:</b></td><td>{_format_sp(char.unallocated_sp)}</td></tr>
            </table>"""

            # Attributes section
            if attrs:
                html += """<h3>Attribute</h3><table cellspacing='4'>
                  <tr><td>🧠 Intelligence:</td><td><b>{}</b></td>
                      <td>📚 Memory:</td><td><b>{}</b></td></tr>
                  <tr><td>👁️ Perception:</td><td><b>{}</b></td>
                      <td>💪 Willpower:</td><td><b>{}</b></td></tr>
                  <tr><td>💬 Charisma:</td><td><b>{}</b></td>
                      <td></td><td></td></tr>
                </table>""".format(
                    attrs.get("intelligence", 0), attrs.get("memory", 0),
                    attrs.get("perception", 0), attrs.get("willpower", 0),
                    attrs.get("charisma", 0),
                )
                if attrs.get("bonus_remaps", 0) > 0:
                    html += f"<p>Bonus Remaps verfügbar: <b>{attrs['bonus_remaps']}</b></p>"

            # Jump Fatigue
            try:
                fatigue = loop.run_until_complete(self.char_service.fetch_fatigue(cid))
                if fatigue:
                    now = datetime.now(UTC)
                    expire = fatigue.jump_fatigue_expire_date
                    last_jump = fatigue.last_jump_date
                    if expire and expire > now:
                        remaining = expire - now
                        hours_left = remaining.total_seconds() / 3600
                        if hours_left > 1:
                            fat_str = f"{int(hours_left)}h {int((remaining.total_seconds() % 3600) / 60)}m"
                        else:
                            fat_str = f"{int(remaining.total_seconds() / 60)}m"
                        fat_color = "{Colors.RED}" if hours_left > 4 else "{Colors.ORANGE}" if hours_left > 1 else "{Colors.ACCENT}"
                        html += (
                            f"<h3>⚡ Jump Fatigue</h3>"
                            f"<table cellspacing='4'>"
                            f"<tr><td>Fatigue-Timer:</td>"
                            f"<td style='color:{fat_color}'><b>{fat_str}</b></td></tr>"
                        )
                        if last_jump:
                            html += f"<tr><td>Letzter Jump:</td><td>{_ts(last_jump)}</td></tr>"
                        html += f"<tr><td>Frei ab:</td><td>{_ts(expire)}</td></tr></table>"
                    elif last_jump:
                        html += (
                            f"<h3>⚡ Jump Fatigue</h3>"
                            f"<p style='color:{Colors.ACCENT}'>✓ Keine Fatigue aktiv</p>"
                            f"<p style='color:{Colors.TEXT_DIM}'>Letzter Jump: {_ts(last_jump)}</p>"
                        )
            except Exception:
                pass  # Fatigue is optional

            # Employment History
            if history:
                html += "<h3>Employment History</h3><table>"
                html += "<tr><th>Corporation</th><th>Beigetreten</th></tr>"
                for h in history[:20]:
                    corp_id = h.get("corporation_id", 0)
                    start = h.get("start_date", "")[:10]
                    html += f"<tr><td>{hist_names.get(corp_id, f'#{corp_id}')}</td><td>{start}</td></tr>"
                html += "</table>"

            self._update_overview.emit(html)
        except Exception as e:
            logger.error("Overview tab error", exc_info=True)
            self._update_overview.emit(f"<p style='color:red'>Fehler: {e}</p>")

    # ══════════════════════════════════════════════════════════════════
    #  SKILL QUEUE TAB – with progress bars
    # ══════════════════════════════════════════════════════════════════

    def _fetch_skill_queue_tab(self, loop: asyncio.AbstractEventLoop, cid: int) -> None:
        try:
            queue = loop.run_until_complete(self.char_service.fetch_skill_queue(cid))
            if not queue:
                self._update_skill_queue.emit("<p>Keine Skills in der Queue.</p>")
                return

            # Check for completed skills (notification)
            self._check_skill_completion(queue)

            now = datetime.now(UTC)
            total_remaining = 0.0
            total_sp_remaining = 0
            for entry in queue:
                if entry.finish_date and entry.finish_date > now:
                    total_remaining += (entry.finish_date - now).total_seconds()
                if entry.level_end_sp > entry.level_start_sp:
                    cur = entry.training_start_sp or entry.level_start_sp
                    if entry.is_training and entry.start_date and entry.finish_date:
                        elapsed = (now - entry.start_date).total_seconds()
                        total_t = (entry.finish_date - entry.start_date).total_seconds()
                        if total_t > 0:
                            sp_g = (entry.level_end_sp - cur) * (elapsed / total_t)
                            cur = int(cur + sp_g)
                    total_sp_remaining += max(0, entry.level_end_sp - cur)

            # Format total time
            total_h = int(total_remaining // 3600)
            total_d = total_h // 24
            remain_h = total_h % 24
            total_str = f"{total_d}d {remain_h}h" if total_d > 0 else f"{total_h}h"

            # Queue completion date
            last_finish = max((e.finish_date for e in queue if e.finish_date), default=None)
            finish_str = f" | Fertig: {_ts(last_finish)}" if last_finish else ""

            html = (
                f"<h3>Skill Queue ({len(queue)} Skills, ~{total_str} verbleibend"
                f" | {total_sp_remaining:,} SP{finish_str})</h3>"
            )

            # Overall queue progress bar
            if queue and queue[-1].finish_date and queue[0].start_date:
                q_total = (queue[-1].finish_date - queue[0].start_date).total_seconds()
                q_elapsed = (now - queue[0].start_date).total_seconds()
                q_pct = max(0, min(100, int(100 * q_elapsed / q_total))) if q_total > 0 else 0
                html += (
                    f"<div style='margin:6px 0'>"
                    f"<div style='background:{Colors.BG_DARK};border:1px solid {Colors.BORDER};border-radius:4px;"
                    f"width:100%;height:18px'>"
                    f"<div style='background:linear-gradient(90deg,{Colors.GREEN},{Colors.ACCENT});"
                    f"width:{q_pct}%;height:100%;border-radius:3px;text-align:center;"
                    f"color:#fff;font-size:11px;line-height:18px'>{q_pct}%</div>"
                    f"</div></div>"
                )

            html += "<table cellspacing='2' style='width:100%'>"
            html += "<tr><th>#</th><th>Skill</th><th>Level</th><th>Fortschritt</th><th>SP</th><th>SP/h</th><th>Restzeit</th></tr>"

            for idx, entry in enumerate(queue, 1):
                level_roman = ["", "I", "II", "III", "IV", "V"][entry.finished_level]

                # Progress calculation
                progress = 0
                current_sp = entry.training_start_sp or entry.level_start_sp
                if entry.level_end_sp > entry.level_start_sp:
                    if entry.is_training and entry.start_date and entry.finish_date:
                        elapsed = (now - entry.start_date).total_seconds()
                        total = (entry.finish_date - entry.start_date).total_seconds()
                        if total > 0:
                            sp_gained = (entry.level_end_sp - (entry.training_start_sp or entry.level_start_sp)) * (elapsed / total)
                            current_sp = int((entry.training_start_sp or entry.level_start_sp) + sp_gained)
                    progress = int(100 * (current_sp - entry.level_start_sp) / (entry.level_end_sp - entry.level_start_sp))
                    progress = max(0, min(100, progress))

                # SP/h calculation
                sp_per_hour = ""
                if entry.is_training and entry.start_date and entry.finish_date:
                    train_secs = (entry.finish_date - entry.start_date).total_seconds()
                    train_sp = entry.level_end_sp - (entry.training_start_sp or entry.level_start_sp)
                    if train_secs > 0:
                        sp_per_hour = f"{int(train_sp / train_secs * 3600):,}"

                # SP display
                sp_display = f"{current_sp:,} / {entry.level_end_sp:,}"

                # Progress bar as HTML
                bar_color = "{Colors.ACCENT}" if entry.is_training else "{Colors.BORDER}"
                glow = "box-shadow:0 0 6px {Colors.ACCENT};" if entry.is_training else ""
                active_marker = " ⚡" if entry.is_training else ""
                row_bg = "background:{Colors.BG_DARKEST};" if entry.is_training else ""
                progress_bar = (
                    f"<div style='background:{Colors.BG_DARK};border:1px solid {Colors.BORDER};border-radius:3px;"
                    f"width:160px;height:16px;display:inline-block;{glow}'>"
                    f"<div style='background:{bar_color};width:{progress}%;height:100%;border-radius:2px;"
                    f"text-align:center;color:#fff;font-size:10px;line-height:16px'>"
                    f"{progress}%</div></div>{active_marker}"
                )

                # Remaining time
                remaining = ""
                if entry.finish_date:
                    secs = max(0, (entry.finish_date - now).total_seconds())
                    d = int(secs // 86400)
                    h = int((secs % 86400) // 3600)
                    m = int((secs % 3600) // 60)
                    if d > 0:
                        remaining = f"{d}d {h}h {m}m"
                    elif h > 0:
                        remaining = f"{h}h {m}m"
                    else:
                        remaining = f"{m}m"

                html += (
                    f"<tr style='{row_bg}'><td>{idx}</td><td><b>{entry.skill_name}</b></td>"
                    f"<td>{level_roman}</td><td>{progress_bar}</td>"
                    f"<td style='font-size:0.85em;color:{Colors.TEXT_DIM}'>{sp_display}</td>"
                    f"<td style='color:{Colors.BLUE}'>{sp_per_hour}</td><td>{remaining}</td></tr>"
                )

            html += "</table>"

            # Update window title with training info
            if queue and queue[0].is_training:
                self._update_title_with_training(queue[0])

            self._update_skill_queue.emit(html)
        except Exception as e:
            logger.error("Skill queue tab error", exc_info=True)
            self._update_skill_queue.emit(f"<p style='color:red'>Fehler: {e}</p>")

    def _update_title_with_training(self, entry) -> None:
        """Update window title with current training info (thread-safe)."""
        if entry.finish_date:
            self._training_finish = entry.finish_date
            self._training_skill_name = entry.skill_name
            self._training_level = entry.finished_level
            QTimer.singleShot(0, self._update_training_countdown)

    def _update_training_countdown(self) -> None:
        """Update window title with remaining training time."""
        if not self._training_finish:
            return
        now = datetime.now(UTC)
        secs = max(0, (self._training_finish - now).total_seconds())
        if secs <= 0:
            self.setWindowTitle("PyMon – Training abgeschlossen!")
            return
        d = int(secs // 86400)
        h = int((secs % 86400) // 3600)
        m = int((secs % 3600) // 60)
        level = ["", "I", "II", "III", "IV", "V"][self._training_level]
        if d > 0:
            time_str = f"{d}d {h}h {m}m"
        else:
            time_str = f"{h}h {m}m"
        self.setWindowTitle(f"PyMon – {self._training_skill_name} {level} ({time_str})")

    def _check_skill_completion(self, new_queue: list) -> None:
        """Check if any skills completed since last check, notify user."""
        if self._prev_skill_queue is None:
            self._prev_skill_queue = [e.skill_id for e in new_queue]
            return

        prev_ids = set(self._prev_skill_queue)
        new_ids = set(e.skill_id for e in new_queue)
        completed = prev_ids - new_ids
        self._prev_skill_queue = [e.skill_id for e in new_queue]

        if not self._tray_icon:
            return

        popup_ms = self.config.tray_show_popup_duration * 1000

        # Skill completion notification
        if completed and self.config.tray_notify_skill_complete:
            names = [self.sde.get_type_name(sid) for sid in completed]
            msg = "Skill-Training abgeschlossen:\n" + "\n".join(f"✓ {n}" for n in names)
            self._tray_icon.showMessage("PyMon – Skill Complete!", msg,
                                        QSystemTrayIcon.MessageIcon.Information, popup_ms)

            # Email notification for completed skills
            if self.config.email_enabled and self._email_notifier.is_configured:
                char_name = self._get_current_char_name()
                for sid in completed:
                    sname = self.sde.get_type_name(sid)
                    self._email_notifier.send_skill_completed(char_name, sname, 0)

        # Empty queue warning
        if not new_queue and prev_ids and self.config.tray_notify_queue_empty:
            self._tray_icon.showMessage(
                "PyMon – Skill Queue leer!",
                "Die Skill Queue ist leer. Füge neue Skills hinzu!",
                QSystemTrayIcon.MessageIcon.Warning, popup_ms,
            )
            # Email notification for empty queue
            if self.config.email_enabled and self._email_notifier.is_configured:
                char_name = self._get_current_char_name()
                self._email_notifier.send_queue_empty(char_name)

    # ══════════════════════════════════════════════════════════════════
    #  SKILLS TAB
    # ══════════════════════════════════════════════════════════════════

    def _fetch_skills_tab(self, loop: asyncio.AbstractEventLoop, cid: int) -> None:
        try:
            skills = loop.run_until_complete(self.char_service.fetch_skills(cid))
            if not skills:
                self._update_skills.emit("<p>Keine Skills.</p>")
                return

            # Group by group_name
            groups: dict[str, list] = {}
            for s in skills:
                groups.setdefault(s.group_name or "Unbekannt", []).append(s)

            level_bars = {0: "○○○○○", 1: "●○○○○", 2: "●●○○○", 3: "●●●○○", 4: "●●●●○", 5: "●●●●●"}

            html = f"<h3>Skills ({len(skills)} trainiert, {sum(s.skillpoints_in_skill for s in skills):,} SP)</h3>"
            for group_name in sorted(groups):
                group_skills = sorted(groups[group_name], key=lambda s: s.skill_name)
                group_sp = sum(s.skillpoints_in_skill for s in group_skills)
                html += f"<h4>{group_name} ({len(group_skills)} Skills, {group_sp:,} SP)</h4>"
                html += "<table>"
                for s in group_skills:
                    lvl = s.active_skill_level
                    html += (
                        f"<tr><td>{s.skill_name}</td>"
                        f"<td><span style='color:{Colors.BLUE}'>{level_bars.get(lvl, '?')}</span></td>"
                        f"<td style='color:{Colors.TEXT_DIM}'>{s.skillpoints_in_skill:,} SP</td></tr>"
                    )
                html += "</table>"

            self._update_skills.emit(html)

            # Update Skill Planner with current character data
            trained = {s.skill_id: s.active_skill_level for s in skills}
            # Fetch attributes for planner (re-use cached if available)
            try:
                planner_attrs = loop.run_until_complete(self.char_service.fetch_attributes(cid))
                attrs_dict = {
                    "intelligence": planner_attrs.get("intelligence", 17),
                    "memory": planner_attrs.get("memory", 17),
                    "perception": planner_attrs.get("perception", 17),
                    "willpower": planner_attrs.get("willpower", 17),
                    "charisma": planner_attrs.get("charisma", 17),
                }
            except Exception:
                attrs_dict = {k: 17 for k in ["intelligence","memory","perception","willpower","charisma"]}
            self._update_skill_planner.emit(attrs_dict, trained, cid)
            self._update_cert_browser.emit(trained, cid)
            self._update_skills_chart.emit(skills)
            self._update_ship_browser.emit(trained)
        except Exception as e:
            logger.error("Skills tab error", exc_info=True)
            self._update_skills.emit(f"<p style='color:red'>Fehler: {e}</p>")

    # ══════════════════════════════════════════════════════════════════
    #  MAIL TAB – with body preview
    # ══════════════════════════════════════════════════════════════════

    def _fetch_mail_tab(self, loop: asyncio.AbstractEventLoop, cid: int) -> None:
        try:
            mail = loop.run_until_complete(self.char_service.fetch_mail(cid))

            # Resolve sender names
            sender_ids = list(set(m.from_id for m in mail if m.from_id))
            if sender_ids:
                sender_names = loop.run_until_complete(self.name_resolver.resolve_many(sender_ids))
            else:
                sender_names = {}

            if not mail:
                self._update_mail.emit("<p>Keine Mails.</p>")
                return

            # Fetch body for first 10 mails
            mail_bodies: dict[int, str] = {}
            for m in mail[:10]:
                try:
                    body = loop.run_until_complete(
                        self.char_service.fetch_mail_body(cid, m.mail_id)
                    )
                    if body:
                        mail_bodies[m.mail_id] = body
                except Exception:
                    pass

            html = f"<h3>Posteingang ({len(mail)} Mails)</h3>"

            for m in mail:
                ts = _ts(m.timestamp)
                read_icon = "📖" if m.is_read else "📩"
                from_name = sender_names.get(m.from_id, f"#{m.from_id}")
                bg = "{Colors.BG_DARK}" if not m.is_read else "{Colors.BG_DARKEST}"

                html += (
                    f"<div style='margin:6px 0;padding:8px;background:{bg};"
                    f"border-radius:4px;border-left:3px solid {'{Colors.BORDER}' if m.is_read else '{Colors.BLUE}'}'>"
                    f"<b>{read_icon} {m.subject}</b><br>"
                    f"<span style='color:{Colors.TEXT_DIM}'>Von: {from_name} | {ts}</span>"
                )

                # Show body if available
                body = mail_bodies.get(m.mail_id, "")
                if body:
                    # Clean up EVE mail HTML (strip font tags, size tags)
                    import re
                    clean = re.sub(r"<font[^>]*>|</font>", "", body)
                    clean = re.sub(r"</?size[^>]*>", "", clean)
                    clean = clean.replace("<br>", "<br>").strip()
                    if len(clean) > 500:
                        clean = clean[:500] + "..."
                    html += f"<div style='margin-top:4px;color:{Colors.TEXT_HEADING};padding:4px 0'>{clean}</div>"

                html += "</div>"

            self._update_mail.emit(html)
        except Exception as e:
            logger.error("Mail tab error", exc_info=True)
            self._update_mail.emit(f"<p style='color:red'>Fehler: {e}</p>")

    # ══════════════════════════════════════════════════════════════════
    #  WALLET TAB – Journal + Transactions
    # ══════════════════════════════════════════════════════════════════

    def _fetch_wallet_tab(self, loop: asyncio.AbstractEventLoop, cid: int) -> None:
        try:
            journal = loop.run_until_complete(self.char_service.fetch_wallet_journal(cid))
            transactions = loop.run_until_complete(self.char_service.fetch_wallet_transactions(cid))

            # ── Resolve all party / client / location IDs upfront ──
            ids_to_resolve: set[int] = set()
            for j in (journal or []):
                if j.first_party_id:
                    ids_to_resolve.add(j.first_party_id)
                if j.second_party_id:
                    ids_to_resolve.add(j.second_party_id)
            for t in (transactions or []):
                if t.client_id:
                    ids_to_resolve.add(t.client_id)
                if t.location_id:
                    ids_to_resolve.add(t.location_id)
            resolved = loop.run_until_complete(
                self.name_resolver.resolve_many(list(ids_to_resolve))
            ) if ids_to_resolve else {}

            html = ""

            # ISK balance summary from journal
            if journal:
                latest_balance = journal[0].balance if journal else 0
                # Calculate income/expense from recent entries
                total_income = sum(j.amount for j in journal if j.amount and j.amount > 0)
                total_expense = sum(j.amount for j in journal if j.amount and j.amount < 0)
                net = total_income + total_expense

                net_color = "{Colors.ACCENT}" if net >= 0 else "{Colors.RED}"
                html += (
                    f"<h3>💰 Wallet – {latest_balance:,.2f} ISK</h3>"
                    f"<table cellspacing='6'>"
                    f"<tr><td>📈 Einnahmen:</td><td style='color:{Colors.ACCENT}'>+{total_income:,.2f} ISK</td>"
                    f"<td>📉 Ausgaben:</td><td style='color:{Colors.RED}'>{total_expense:,.2f} ISK</td>"
                    f"<td>📊 Bilanz:</td><td style='color:{net_color}'>{net:+,.2f} ISK</td></tr>"
                    f"</table>"
                )

                # ISK balance sparkline (ASCII bar chart from journal balances)
                balances = [j.balance for j in reversed(journal) if j.balance]
                if len(balances) >= 3:
                    # Sample up to 40 data points
                    step = max(1, len(balances) // 40)
                    sampled = balances[::step][-40:]
                    min_b = min(sampled)
                    max_b = max(sampled)
                    rng = max_b - min_b if max_b > min_b else 1

                    html += "<div style='margin:8px 0;padding:8px;background:{Colors.BG_DARKEST};border-radius:6px'>"
                    html += "<p style='margin:0 0 4px 0;color:{Colors.TEXT_DIM};font-size:0.85em'>ISK-Verlauf (Journal)</p>"
                    html += "<div style='display:flex;align-items:flex-end;height:60px;gap:1px'>"
                    for val in sampled:
                        pct = max(3, int(100 * (val - min_b) / rng))
                        color = "{Colors.ACCENT}" if val >= sampled[-1] * 0.95 else "{Colors.BORDER}"
                        html += (
                            f"<div style='width:4px;height:{pct}%;background:{color};"
                            f"border-radius:1px' title='{val:,.0f} ISK'></div>"
                        )
                    html += "</div>"
                    html += (
                        f"<div style='display:flex;justify-content:space-between;color:{Colors.TEXT_DIM};font-size:0.75em'>"
                        f"<span>{sampled[0]:,.0f}</span><span>{sampled[-1]:,.0f}</span></div>"
                    )
                    html += "</div>"

            # Journal
            if journal:
                html += "<h3>Wallet Journal (letzte 50)</h3><table>"
                html += "<tr><th>Datum</th><th>Typ</th><th>Von</th><th>An</th><th>Betrag</th><th>Saldo</th><th>Beschreibung</th></tr>"
                for j in journal[:50]:
                    ts = _ts(j.date)
                    amt_color = "{Colors.ACCENT}" if j.amount and j.amount >= 0 else "{Colors.RED}"
                    amt_str = f"+{j.amount:,.2f}" if j.amount and j.amount >= 0 else f"{j.amount:,.2f}"
                    first_name = resolved.get(j.first_party_id, "") if j.first_party_id else ""
                    second_name = resolved.get(j.second_party_id, "") if j.second_party_id else ""
                    html += (
                        f"<tr><td>{ts}</td><td>{j.ref_type}</td>"
                        f"<td>{first_name}</td><td>{second_name}</td>"
                        f"<td style='color:{amt_color}'>{amt_str}</td>"
                        f"<td>{j.balance:,.2f}</td>"
                        f"<td>{j.description}</td></tr>"
                    )
                html += "</table>"
            else:
                html += "<p>Kein Wallet Journal.</p>"

            # Transactions
            if transactions:
                html += "<h3>Transaktionen</h3><table>"
                html += "<tr><th>Datum</th><th>Gegenstand</th><th>Menge</th><th>Preis/Stk</th><th>Gesamt</th><th>Typ</th><th>Kunde</th><th>Standort</th></tr>"
                for t in transactions[:50]:
                    ts = _ts(t.date)
                    total = t.quantity * t.unit_price
                    buy_sell = "🔴 Kauf" if t.is_buy else "🟢 Verkauf"
                    color = "{Colors.RED}" if t.is_buy else "{Colors.ACCENT}"
                    client_name = resolved.get(t.client_id, "") if t.client_id else ""
                    loc_name = resolved.get(t.location_id, "") if t.location_id else ""
                    html += (
                        f"<tr><td>{ts}</td><td>{t.type_name}</td><td>{t.quantity:,}</td>"
                        f"<td>{t.unit_price:,.2f}</td>"
                        f"<td style='color:{color}'>{total:,.2f}</td>"
                        f"<td>{buy_sell}</td>"
                        f"<td>{client_name}</td><td>{loc_name}</td></tr>"
                    )
                html += "</table>"

            self._update_wallet.emit(html)
            # Feed wallet chart with journal data
            if journal:
                self._update_wallet_chart.emit(journal)
            # Feed trade tracker with transaction data
            if transactions:
                tx_dicts = [
                    {
                        "type_id": t.type_id,
                        "type_name": t.type_name,
                        "quantity": t.quantity,
                        "unit_price": t.unit_price,
                        "is_buy": t.is_buy,
                        "date": t.date,
                    }
                    for t in transactions
                ]
                self._update_trade_tracker.emit(tx_dicts)
        except Exception as e:
            self._update_wallet.emit(f"<p style='color:red'>Fehler: {e}</p>")

    # ══════════════════════════════════════════════════════════════════
    #  ASSETS TAB – with location names
    # ══════════════════════════════════════════════════════════════════

    def _fetch_assets_tab(self, loop: asyncio.AbstractEventLoop, cid: int) -> None:
        try:
            assets = loop.run_until_complete(self.char_service.fetch_assets(cid))
            if not assets:
                self._update_assets.emit("<p>Keine Assets.</p>")
                return

            # Resolve location IDs (stations, citadels, solar systems – but not items inside containers)
            loc_ids = list(set(
                a.location_id for a in assets
                if a.location_id and a.location_type != "item"
            ))
            if loc_ids:
                loc_names = loop.run_until_complete(self.name_resolver.resolve_many(loc_ids))
            else:
                loc_names = {}

            # Group by location
            by_location: dict[int, list] = {}
            for a in assets:
                by_location.setdefault(a.location_id, []).append(a)

            # Estimate ISK values from SDE base_price
            total_value = 0.0
            location_values: dict[int, float] = {}
            for loc_id, items in by_location.items():
                loc_val = 0.0
                for a in items:
                    base = self.sde.get_type(a.type_id)
                    if base and base.get("base_price"):
                        val = base["base_price"] * a.quantity
                        loc_val += val
                        total_value += val
                location_values[loc_id] = loc_val

            html = f"<h3>Assets ({len(assets)} Gegenstände | ~{total_value:,.0f} ISK Basiswert)</h3>"

            # Sort locations by value (highest first)
            sorted_locs = sorted(by_location.keys(),
                                 key=lambda lid: location_values.get(lid, 0), reverse=True)

            for loc_id in sorted_locs:
                items = by_location[loc_id]
                items_sorted = sorted(items, key=lambda a: a.type_name)
                loc_name = loc_names.get(loc_id, f"Location #{loc_id}")
                loc_val = location_values.get(loc_id, 0)
                val_str = f" | ~{loc_val:,.0f} ISK" if loc_val > 0 else ""

                html += f"<h4>📦 {loc_name} ({len(items)} Items{val_str})</h4><table>"
                html += "<tr><th>Gegenstand</th><th>Menge</th><th>Kategorie</th><th>~ISK</th></tr>"
                for a in items_sorted[:150]:
                    base = self.sde.get_type(a.type_id)
                    item_val = (base["base_price"] * a.quantity) if base and base.get("base_price") else 0
                    val_cell = f"{item_val:,.0f}" if item_val > 0 else "-"
                    bpc_tag = " 📋BPC" if a.is_blueprint_copy else ""
                    html += (
                        f"<tr><td>{a.type_name}{bpc_tag}</td><td>{a.quantity:,}</td>"
                        f"<td>{a.location_flag}</td><td style='text-align:right'>{val_cell}</td></tr>"
                    )
                if len(items) > 150:
                    html += f"<tr><td colspan='4'><i>...und {len(items) - 150} weitere</i></td></tr>"
                html += "</table>"

            self._update_assets.emit(html)

            # Also update Owned Skill Books widget
            try:
                skills = loop.run_until_complete(self.char_service.fetch_skills(cid))
                trained = {s.skill_id: s.active_skill_level for s in skills}
                self._update_skill_books.emit(assets, trained, loc_names)
            except Exception:
                logger.debug("Skill books update skipped", exc_info=True)
        except Exception as e:
            logger.error("Assets tab error", exc_info=True)
            self._update_assets.emit(f"<p style='color:red'>Fehler: {e}</p>")

    # ══════════════════════════════════════════════════════════════════
    #  CONTRACTS TAB
    # ══════════════════════════════════════════════════════════════════

    def _fetch_contracts_tab(self, loop: asyncio.AbstractEventLoop, cid: int) -> None:
        try:
            contracts = loop.run_until_complete(self.char_service.fetch_contracts(cid))
            if not contracts:
                self._update_contracts.emit("<p>Keine Contracts.</p>")
                return

            self._contracts_cache = contracts  # store for detail popup

            # Resolve issuer/assignee/location names
            all_ids = list(set(
                [c.issuer_id for c in contracts if c.issuer_id]
                + [c.assignee_id for c in contracts if c.assignee_id]
                + [c.acceptor_id for c in contracts if c.acceptor_id]
                + [c.start_location_id for c in contracts if c.start_location_id]
                + [c.end_location_id for c in contracts if c.end_location_id]
            ))
            names = loop.run_until_complete(self.name_resolver.resolve_many(all_ids)) if all_ids else {}
            self._contract_names_cache = names  # for detail popup

            type_icons = {
                "item_exchange": "📦", "auction": "🔨", "courier": "🚚", "loan": "💰",
            }
            status_colors = {
                "outstanding": "{Colors.BLUE}", "in_progress": "{Colors.ORANGE}",
                "finished": "{Colors.ACCENT}", "finished_issuer": "{Colors.ACCENT}",
                "finished_contractor": "{Colors.ACCENT}", "cancelled": "{Colors.RED}",
                "rejected": "{Colors.RED}", "failed": "{Colors.RED}",
                "deleted": "{Colors.TEXT_DIM}", "reversed": "{Colors.ORANGE}",
            }

            html = f"<h3>📋 Contracts ({len(contracts)})</h3>"
            html += "<p style='color:{Colors.TEXT_DIM}'>Klicke auf einen Contract für Details.</p>"
            html += "<table>"
            html += "<tr><th>Typ</th><th>Status</th><th>Titel</th><th>Ersteller</th><th>Empfänger</th><th>Preis</th><th>Ablauf</th></tr>"
            for c in contracts:
                exp = _ts(c.date_expired, "%Y-%m-%d") if c.date_expired else "-"
                issuer = names.get(c.issuer_id, f"#{c.issuer_id}")
                assignee = names.get(c.assignee_id, "") if c.assignee_id else ""
                icon = type_icons.get(c.contract_type, "📄")
                s_color = status_colors.get(c.status, "{Colors.TEXT_HEADING}")
                title_disp = c.title or f"[{c.contract_type}]"
                html += (
                    f"<tr>"
                    f"<td>{icon} {c.contract_type}</td>"
                    f"<td style='color:{s_color}'>{c.status}</td>"
                    f"<td><a href='contract:{c.contract_id}' style='color:{Colors.BLUE}'>{title_disp}</a></td>"
                    f"<td>{issuer}</td>"
                    f"<td>{assignee}</td>"
                    f"<td style='text-align:right'>{c.price:,.2f} ISK</td>"
                    f"<td>{exp}</td>"
                    f"</tr>"
                )
            html += "</table>"

            self._update_contracts.emit(html)
        except Exception as e:
            logger.error("Contracts tab error", exc_info=True)
            self._update_contracts.emit(f"<p style='color:red'>Fehler: {e}</p>")

    def _on_contract_link(self, url: str) -> None:
        """Handle clicks on contract links – show detail popup."""
        if not url.startswith("contract:"):
            return
        try:
            contract_id = int(url.split(":")[1])
        except (ValueError, IndexError):
            return

        # Find contract in cache
        contract = None
        for c in self._contracts_cache:
            if c.contract_id == contract_id:
                contract = c
                break
        if not contract:
            return

        # Fetch items in background thread
        import threading

        def _load() -> None:
            try:
                loop = asyncio.new_event_loop()
                cid = self._current_character_id
                items = loop.run_until_complete(
                    self.char_service.fetch_contract_items(cid, contract_id)
                )
                loop.close()
                # Build detail dialog on main thread
                self._show_contract_detail.emit(contract, items)
            except Exception:
                logger.error("Contract detail error", exc_info=True)

        threading.Thread(target=_load, daemon=True).start()

    def _display_contract_detail(self, contract, items) -> None:
        """Show a contract detail dialog (called on main thread via signal)."""
        from PySide6.QtWidgets import QDialog, QVBoxLayout

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Contract #{contract.contract_id}")
        dlg.setMinimumSize(500, 400)

        layout = QVBoxLayout(dlg)
        label = QLabel()
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignTop)

        type_icons = {
            "item_exchange": "📦 Item Exchange", "auction": "🔨 Auction",
            "courier": "🚚 Courier", "loan": "💰 Loan",
        }

        html = f"<h3>{type_icons.get(contract.contract_type, contract.contract_type)}</h3>"
        if contract.title:
            html += f"<p style='font-size:14px'><b>{contract.title}</b></p>"
        html += "<table>"
        html += f"<tr><td><b>Status</b></td><td>{contract.status}</td></tr>"

        # Resolve names from cache
        _cn = getattr(self, "_contract_names_cache", {})
        if contract.issuer_id:
            html += f"<tr><td><b>Ersteller</b></td><td>{_cn.get(contract.issuer_id, f'#{contract.issuer_id}')}</td></tr>"
        if contract.assignee_id:
            html += f"<tr><td><b>Empfänger</b></td><td>{_cn.get(contract.assignee_id, f'#{contract.assignee_id}')}</td></tr>"
        if contract.acceptor_id:
            html += f"<tr><td><b>Angenommen von</b></td><td>{_cn.get(contract.acceptor_id, f'#{contract.acceptor_id}')}</td></tr>"

        if contract.price:
            html += f"<tr><td><b>Preis</b></td><td>{contract.price:,.2f} ISK</td></tr>"
        if contract.reward:
            html += f"<tr><td><b>Belohnung</b></td><td>{contract.reward:,.2f} ISK</td></tr>"
        if contract.collateral:
            html += f"<tr><td><b>Sicherheit</b></td><td>{contract.collateral:,.2f} ISK</td></tr>"
        if contract.buyout:
            html += f"<tr><td><b>Sofortkauf</b></td><td>{contract.buyout:,.2f} ISK</td></tr>"
        if contract.volume:
            html += f"<tr><td><b>Volumen</b></td><td>{contract.volume:,.0f} m³</td></tr>"

        # Start/End locations for courier contracts
        if contract.start_location_id:
            start_loc = _cn.get(contract.start_location_id, f"Standort #{contract.start_location_id}")
            html += f"<tr><td><b>Startort</b></td><td>{start_loc}</td></tr>"
        if contract.end_location_id:
            end_loc = _cn.get(contract.end_location_id, f"Standort #{contract.end_location_id}")
            html += f"<tr><td><b>Zielort</b></td><td>{end_loc}</td></tr>"

        if contract.date_issued:
            html += f"<tr><td><b>Erstellt</b></td><td>{contract.date_issued:%Y-%m-%d %H:%M}</td></tr>"
        if contract.date_expired:
            html += f"<tr><td><b>Ablauf</b></td><td>{contract.date_expired:%Y-%m-%d %H:%M}</td></tr>"
        if contract.date_accepted:
            html += f"<tr><td><b>Akzeptiert</b></td><td>{contract.date_accepted:%Y-%m-%d %H:%M}</td></tr>"
        if contract.date_completed:
            html += f"<tr><td><b>Abgeschlossen</b></td><td>{contract.date_completed:%Y-%m-%d %H:%M}</td></tr>"
        html += "</table>"

        # Items
        if items:
            included = [i for i in items if i.get("is_included", True)]
            requested = [i for i in items if not i.get("is_included", True)]

            if included:
                html += f"<h4>📦 Enthaltene Items ({len(included)})</h4><table>"
                html += "<tr><th>Item</th><th style='text-align:right'>Menge</th></tr>"
                for it in sorted(included, key=lambda x: x.get("type_name", "")):
                    qty = it.get("quantity", 1)
                    name = it.get("type_name", f"Type #{it.get('type_id', '?')}")
                    html += f"<tr><td>{name}</td><td style='text-align:right'>{qty:,}</td></tr>"
                html += "</table>"

            if requested:
                html += f"<h4>🔁 Angeforderte Items ({len(requested)})</h4><table>"
                html += "<tr><th>Item</th><th style='text-align:right'>Menge</th></tr>"
                for it in sorted(requested, key=lambda x: x.get("type_name", "")):
                    qty = it.get("quantity", 1)
                    name = it.get("type_name", f"Type #{it.get('type_id', '?')}")
                    html += f"<tr><td>{name}</td><td style='text-align:right'>{qty:,}</td></tr>"
                html += "</table>"
        else:
            html += "<p style='color:{Colors.TEXT_DIM}'>Keine Items in diesem Contract.</p>"

        label.setText(html)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(label)
        layout.addWidget(scroll)

        dlg.exec()

    # ══════════════════════════════════════════════════════════════════
    #  INDUSTRY TAB
    # ══════════════════════════════════════════════════════════════════

    def _fetch_industry_tab(self, loop: asyncio.AbstractEventLoop, cid: int) -> None:
        try:
            jobs = loop.run_until_complete(self.char_service.fetch_industry_jobs(cid))
            if not jobs:
                self._update_industry.emit("<p>Keine Industrie-Jobs.</p>")
                return

            # Resolve facility/station IDs for location names
            fac_ids: set[int] = set()
            for j in jobs:
                if j.facility_id:
                    fac_ids.add(j.facility_id)
                if j.station_id:
                    fac_ids.add(j.station_id)
            fac_names = loop.run_until_complete(
                self.name_resolver.resolve_many(list(fac_ids))
            ) if fac_ids else {}

            activity_names = {1: "🔨 Herstellung", 3: "⏱️ TE-Forschung", 4: "🧪 ME-Forschung",
                              5: "📋 Kopieren", 8: "💡 Invention", 9: "⚗️ Reaktion",
                              11: "🔄 Reverse Engineering"}

            now = datetime.now(UTC)

            # Separate active and completed
            active = [j for j in jobs if j.status == "active"]
            ready = [j for j in jobs if j.status == "ready"]
            other = [j for j in jobs if j.status not in ("active", "ready")]

            html = (
                f"<h3>Industrie-Jobs ({len(jobs)}: "
                f"🟢 {len(active)} aktiv, ✅ {len(ready)} fertig"
                f"{f', 📦 {len(other)} andere' if other else ''})</h3>"
            )

            def _job_location(j) -> str:
                """Best location name for an industry job."""
                return fac_names.get(j.facility_id, fac_names.get(j.station_id, ""))

            # Active jobs with progress bars and timers
            if active:
                html += "<h4>🟢 Aktive Jobs</h4><table style='width:100%'>"
                html += "<tr><th>Aktivität</th><th>Blueprint</th><th>Runs</th><th>Standort</th><th>Fortschritt</th><th>Restzeit</th></tr>"
                for j in sorted(active, key=lambda x: x.end_date or now):
                    activity = activity_names.get(j.activity_id, f"#{j.activity_id}")

                    # Progress bar
                    progress = 0
                    remaining = ""
                    if j.start_date and j.end_date:
                        total_secs = (j.end_date - j.start_date).total_seconds()
                        elapsed_secs = (now - j.start_date).total_seconds()
                        if total_secs > 0:
                            progress = max(0, min(100, int(100 * elapsed_secs / total_secs)))

                        secs_left = max(0, (j.end_date - now).total_seconds())
                        d = int(secs_left // 86400)
                        h = int((secs_left % 86400) // 3600)
                        m = int((secs_left % 3600) // 60)
                        if d > 0:
                            remaining = f"{d}d {h}h {m}m"
                        elif h > 0:
                            remaining = f"{h}h {m}m"
                        else:
                            remaining = f"{m}m"

                    # Color by progress
                    if progress >= 90:
                        bar_color = "{Colors.GREEN}"
                    elif progress >= 50:
                        bar_color = "{Colors.ACCENT}"
                    else:
                        bar_color = "#1f6feb"

                    progress_bar = (
                        f"<div style='background:{Colors.BG_DARK};border:1px solid {Colors.BORDER};border-radius:3px;"
                        f"width:140px;height:16px;display:inline-block'>"
                        f"<div style='background:{bar_color};width:{progress}%;height:100%;"
                        f"border-radius:2px;text-align:center;color:#fff;font-size:10px;"
                        f"line-height:16px'>{progress}%</div></div>"
                    )

                    html += (
                        f"<tr><td>{activity}</td><td><b>{j.blueprint_type_name}</b></td>"
                        f"<td>{j.runs}</td><td>{_job_location(j)}</td><td>{progress_bar}</td>"
                        f"<td style='color:{Colors.ORANGE}'>{remaining}</td></tr>"
                    )
                html += "</table>"

            # Ready (completed but not delivered)
            if ready:
                html += "<h4>✅ Fertige Jobs (zur Abholung bereit)</h4><table>"
                html += "<tr><th>Aktivität</th><th>Blueprint</th><th>Runs</th><th>Standort</th><th>Fertig seit</th></tr>"
                for j in ready:
                    activity = activity_names.get(j.activity_id, f"#{j.activity_id}")
                    end = _ts(j.end_date)
                    html += (
                        f"<tr style='color:{Colors.ACCENT}'><td>{activity}</td>"
                        f"<td><b>{j.blueprint_type_name}</b></td>"
                        f"<td>{j.runs}</td><td>{_job_location(j)}</td><td>{end}</td></tr>"
                    )
                html += "</table>"

            # Other statuses
            if other:
                html += "<h4>📦 Sonstige Jobs</h4><table>"
                html += "<tr><th>Aktivität</th><th>Blueprint</th><th>Status</th><th>Runs</th><th>Standort</th><th>Ende</th></tr>"
                for j in other:
                    activity = activity_names.get(j.activity_id, f"#{j.activity_id}")
                    status_icon = {"delivered": "📬", "cancelled": "❌", "paused": "⏸️",
                                   "reverted": "↩️"}.get(j.status, "❓")
                    end = _ts(j.end_date)
                    html += (
                        f"<tr><td>{activity}</td><td>{j.blueprint_type_name}</td>"
                        f"<td>{status_icon} {j.status}</td><td>{j.runs}</td><td>{_job_location(j)}</td><td>{end}</td></tr>"
                    )
                html += "</table>"

            self._update_industry.emit(html)

            # Feed trade advisor with manufacturing products (activity=1)
            manufacturing_products = [
                {
                    "product_type_id": j.product_type_id if hasattr(j, "product_type_id") else 0,
                    "type_id": j.blueprint_type_id if hasattr(j, "blueprint_type_id") else 0,
                    "runs": j.runs,
                }
                for j in jobs
                if j.activity_id == 1 and j.status in ("active", "ready", "delivered")
            ]
            if manufacturing_products:
                self._update_trade_advisor_industry.emit(manufacturing_products)
        except Exception as e:
            logger.error("Industry tab error", exc_info=True)
            self._update_industry.emit(f"<p style='color:red'>Fehler: {e}</p>")

    # ══════════════════════════════════════════════════════════════════
    #  MARKET ORDERS TAB
    # ══════════════════════════════════════════════════════════════════

    def _fetch_market_tab(self, loop: asyncio.AbstractEventLoop, cid: int) -> None:
        try:
            orders = loop.run_until_complete(self.char_service.fetch_market_orders(cid))

            buy = [o for o in orders if o.is_buy_order]
            sell = [o for o in orders if not o.is_buy_order]

            # Resolve location and region IDs
            loc_ids: set[int] = set()
            for o in orders:
                if o.location_id:
                    loc_ids.add(o.location_id)
                if o.region_id:
                    loc_ids.add(o.region_id)
            order_names = loop.run_until_complete(
                self.name_resolver.resolve_many(list(loc_ids))
            ) if loc_ids else {}

            # Calculate totals
            sell_value = sum(o.price * o.volume_remain for o in sell)
            buy_escrow = sum(o.escrow for o in buy)
            total_volume = sum(o.volume_remain for o in orders)

            html = (
                f"<h3>📊 Markt-Orders ({len(orders)}: "
                f"🟢 {len(sell)} Sell, 🔴 {len(buy)} Buy)</h3>"
            )

            if orders:
                html += (
                    f"<table cellspacing='6'>"
                    f"<tr><td>💰 Sell-Wert:</td><td style='color:{Colors.ACCENT}'>{sell_value:,.2f} ISK</td>"
                    f"<td>🔒 Buy-Escrow:</td><td style='color:{Colors.ORANGE}'>{buy_escrow:,.2f} ISK</td>"
                    f"<td>📦 Verbleibend:</td><td>{total_volume:,} Stk</td></tr>"
                    f"</table>"
                )

            now = datetime.now(UTC)

            if sell:
                html += "<h4>🟢 Sell Orders</h4><table style='width:100%'>"
                html += "<tr><th>Gegenstand</th><th>Preis</th><th>Menge</th><th>Fortschritt</th><th>Standort</th><th>Ablauf</th></tr>"
                for o in sorted(sell, key=lambda x: x.price * x.volume_remain, reverse=True):
                    sell_loc = order_names.get(o.location_id, "") if o.location_id else ""
                    # Volume progress
                    vol_pct = 0
                    if o.volume_total > 0:
                        vol_pct = int(100 * (o.volume_total - o.volume_remain) / o.volume_total)
                    vol_bar = (
                        f"<div style='display:inline-block;width:60px;height:12px;"
                        f"background:{Colors.BG_DARK};border:1px solid {Colors.BORDER};border-radius:3px'>"
                        f"<div style='width:{vol_pct}%;height:100%;background:{Colors.ACCENT};"
                        f"border-radius:2px'></div></div> {vol_pct}%"
                    )
                    # Days until expiry
                    expiry = ""
                    if o.issued and o.duration > 0:
                        from datetime import timedelta
                        exp_date = o.issued + timedelta(days=o.duration)
                        days_left = max(0, (exp_date - now).days)
                        if days_left <= 3:
                            expiry = f"<span style='color:{Colors.RED}'>⚠️ {days_left}d</span>"
                        elif days_left <= 7:
                            expiry = f"<span style='color:{Colors.ORANGE}'>{days_left}d</span>"
                        else:
                            expiry = f"{days_left}d"
                    html += (
                        f"<tr><td>{o.type_name}</td>"
                        f"<td style='text-align:right'>{o.price:,.2f}</td>"
                        f"<td>{o.volume_remain}/{o.volume_total}</td>"
                        f"<td>{vol_bar}</td>"
                        f"<td>{sell_loc}</td>"
                        f"<td>{expiry}</td></tr>"
                    )
                html += "</table>"

            if buy:
                html += "<h4>🔴 Buy Orders</h4><table style='width:100%'>"
                html += "<tr><th>Gegenstand</th><th>Preis</th><th>Menge</th><th>Fortschritt</th><th>Standort</th><th>Escrow</th><th>Ablauf</th></tr>"
                for o in sorted(buy, key=lambda x: x.escrow, reverse=True):
                    buy_loc = order_names.get(o.location_id, "") if o.location_id else ""
                    vol_pct = 0
                    if o.volume_total > 0:
                        vol_pct = int(100 * (o.volume_total - o.volume_remain) / o.volume_total)
                    vol_bar = (
                        f"<div style='display:inline-block;width:60px;height:12px;"
                        f"background:{Colors.BG_DARK};border:1px solid {Colors.BORDER};border-radius:3px'>"
                        f"<div style='width:{vol_pct}%;height:100%;background:{Colors.ORANGE};"
                        f"border-radius:2px'></div></div> {vol_pct}%"
                    )
                    expiry = ""
                    if o.issued and o.duration > 0:
                        from datetime import timedelta
                        exp_date = o.issued + timedelta(days=o.duration)
                        days_left = max(0, (exp_date - now).days)
                        if days_left <= 3:
                            expiry = f"<span style='color:{Colors.RED}'>⚠️ {days_left}d</span>"
                        elif days_left <= 7:
                            expiry = f"<span style='color:{Colors.ORANGE}'>{days_left}d</span>"
                        else:
                            expiry = f"{days_left}d"
                    html += (
                        f"<tr><td>{o.type_name}</td>"
                        f"<td style='text-align:right'>{o.price:,.2f}</td>"
                        f"<td>{o.volume_remain}/{o.volume_total}</td>"
                        f"<td>{vol_bar}</td>"
                        f"<td>{buy_loc}</td>"
                        f"<td style='color:{Colors.ORANGE}'>{o.escrow:,.2f}</td>"
                        f"<td>{expiry}</td></tr>"
                    )
                html += "</table>"

            if not orders:
                html += "<p>Keine Markt-Orders.</p>"

            self._update_market.emit(html)
        except Exception as e:
            logger.error("Market tab error", exc_info=True)
            self._update_market.emit(f"<p style='color:red'>Fehler: {e}</p>")

    # ══════════════════════════════════════════════════════════════════
    #  FITTINGS TAB
    # ══════════════════════════════════════════════════════════════════

    def _fetch_fittings_tab(self, loop: asyncio.AbstractEventLoop, cid: int) -> None:
        try:
            fittings = loop.run_until_complete(self.char_service.fetch_fittings(cid))
            if not fittings:
                self._update_fittings.emit("<p>Keine gespeicherten Fittings.</p>")
                return

            # Slot categories for grouping
            def _slot_category(flag: str) -> tuple[int, str]:
                f = flag.lower()
                if f.startswith("hislot"):
                    return (0, "High Slots")
                elif f.startswith("medslot"):
                    return (1, "Med Slots")
                elif f.startswith("loslot"):
                    return (2, "Low Slots")
                elif f.startswith("rigslot"):
                    return (3, "Rig Slots")
                elif f.startswith("subsystemslot"):
                    return (4, "Subsystems")
                elif f == "dronebay":
                    return (5, "Drone Bay")
                elif f == "cargo":
                    return (6, "Cargo")
                elif f == "fighterbay":
                    return (7, "Fighter Bay")
                return (8, "Andere")

            html = f"<h3>Gespeicherte Fittings ({len(fittings)})</h3>"

            for fit in sorted(fittings, key=lambda x: x.name):
                html += (
                    f"<div style='margin:8px 0;padding:10px;background:{Colors.BG_DARK};"
                    f"border-radius:6px;border-left:3px solid {Colors.BLUE}'>"
                    f"<h4 style='margin:0'>🚀 {fit.name}</h4>"
                    f"<p style='color:{Colors.TEXT_DIM};margin:2px 0'>{fit.ship_type_name}</p>"
                )
                if fit.description:
                    html += f"<p style='color:{Colors.TEXT_DIM};font-style:italic'>{fit.description}</p>"

                # Group items by slot
                by_slot: dict[tuple[int, str], list] = {}
                for item in fit.items:
                    cat = _slot_category(item.flag)
                    by_slot.setdefault(cat, []).append(item)

                for (order, slot_name) in sorted(by_slot.keys()):
                    slot_items = by_slot[(order, slot_name)]
                    slot_icon = {"High Slots": "🔴", "Med Slots": "🔵", "Low Slots": "🟢",
                                 "Rig Slots": "🔧", "Subsystems": "⚙️", "Drone Bay": "🐝",
                                 "Cargo": "📦", "Fighter Bay": "✈️"}.get(slot_name, "•")
                    html += f"<p style='margin:4px 0'><b>{slot_icon} {slot_name}</b></p><ul style='margin:2px 0'>"
                    for item in slot_items:
                        qty = f" ×{item.quantity}" if item.quantity > 1 else ""
                        html += f"<li>{item.type_name}{qty}</li>"
                    html += "</ul>"

                # EFT format block
                eft_lines = [f"[{fit.ship_type_name}, {fit.name}]"]
                for (order, _) in sorted(by_slot.keys()):
                    for item in by_slot.get((order, _), []):
                        if item.quantity > 1:
                            eft_lines.append(f"{item.type_name} x{item.quantity}")
                        else:
                            eft_lines.append(item.type_name)
                    eft_lines.append("")  # empty line between slot groups

                html += (
                    f"<details style='margin-top:6px'><summary style='cursor:pointer;color:{Colors.BLUE}'>"
                    f"📋 EFT-Format</summary>"
                    f"<pre style='background:{Colors.BG_DARKEST};padding:8px;border-radius:4px;font-size:11px'>"
                )
                html += "\n".join(eft_lines)
                html += "</pre></details></div>"

            self._update_fittings.emit(html)
        except Exception as e:
            logger.error("Fittings tab error", exc_info=True)
            self._update_fittings.emit(f"<p style='color:red'>Fehler: {e}</p>")

    # ══════════════════════════════════════════════════════════════════
    #  BLUEPRINTS TAB
    # ══════════════════════════════════════════════════════════════════

    def _fetch_blueprints_tab(self, loop: asyncio.AbstractEventLoop, cid: int) -> None:
        try:
            bps = loop.run_until_complete(self.char_service.fetch_blueprints(cid))
            if not bps:
                self._update_blueprints.emit("<p>Keine Blueprints.</p>")
                return

            # Resolve location IDs
            bp_loc_ids = list(set(b.location_id for b in bps if b.location_id))
            bp_loc_names = loop.run_until_complete(
                self.name_resolver.resolve_many(bp_loc_ids)
            ) if bp_loc_ids else {}

            bpos = [b for b in bps if b.is_original]
            bpcs = [b for b in bps if b.is_copy]

            # Count fully researched
            max_me = [b for b in bpos if b.material_efficiency >= 10]
            max_te = [b for b in bpos if b.time_efficiency >= 20]

            html = (
                f"<h3>📘 Blueprints ({len(bps)}: "
                f"📗 {len(bpos)} BPOs, 📋 {len(bpcs)} BPCs"
                f" | ✅ {len(max_me)} max ME, {len(max_te)} max TE)</h3>"
            )

            def _me_te_bar(value: int, max_val: int, color: str) -> str:
                """Render ME or TE as colored progress bar."""
                pct = int(100 * value / max_val) if max_val > 0 else 0
                full_color = "{Colors.GREEN}" if pct >= 100 else color
                return (
                    f"<div style='display:inline-block;width:60px;height:12px;"
                    f"background:{Colors.BG_DARK};border:1px solid {Colors.BORDER};border-radius:3px'>"
                    f"<div style='width:{pct}%;height:100%;background:{full_color};"
                    f"border-radius:2px'></div></div>"
                    f" <span style='color:{full_color}'>{value}%</span>"
                )

            # BPOs first
            if bpos:
                html += "<h4>📗 Blueprint Originals</h4><table>"
                html += "<tr><th>Name</th><th>ME</th><th>TE</th><th>Standort</th><th>Status</th></tr>"
                for b in sorted(bpos, key=lambda x: x.type_name)[:200]:
                    me_bar = _me_te_bar(b.material_efficiency, 10, "#1f6feb")
                    te_bar = _me_te_bar(b.time_efficiency, 20, "#8957e5")
                    bp_loc = bp_loc_names.get(b.location_id, "") if b.location_id else ""
                    status = ""
                    if b.material_efficiency >= 10 and b.time_efficiency >= 20:
                        status = "✅ Perfekt"
                    elif b.material_efficiency >= 10:
                        status = "🔵 ME max"
                    elif b.time_efficiency >= 20:
                        status = "🟣 TE max"
                    else:
                        status = "🔬 Forschbar"
                    html += (
                        f"<tr><td>📗 {b.type_name}</td>"
                        f"<td>{me_bar}</td><td>{te_bar}</td>"
                        f"<td>{bp_loc}</td><td>{status}</td></tr>"
                    )
                if len(bpos) > 200:
                    html += f"<tr><td colspan='5'><i>...und {len(bpos) - 200} weitere BPOs</i></td></tr>"
                html += "</table>"

            # BPCs
            if bpcs:
                html += "<h4>📋 Blueprint Copies</h4><table>"
                html += "<tr><th>Name</th><th>ME</th><th>TE</th><th>Standort</th><th>Runs</th></tr>"
                for b in sorted(bpcs, key=lambda x: x.type_name)[:200]:
                    me_bar = _me_te_bar(b.material_efficiency, 10, "#1f6feb")
                    te_bar = _me_te_bar(b.time_efficiency, 20, "#8957e5")
                    bp_loc = bp_loc_names.get(b.location_id, "") if b.location_id else ""
                    html += (
                        f"<tr><td>📋 {b.type_name}</td>"
                        f"<td>{me_bar}</td><td>{te_bar}</td>"
                        f"<td>{bp_loc}</td><td>{b.runs} Runs</td></tr>"
                    )
                if len(bpcs) > 200:
                    html += f"<tr><td colspan='5'><i>...und {len(bpcs) - 200} weitere BPCs</i></td></tr>"
                html += "</table>"

            self._update_blueprints.emit(html)
        except Exception as e:
            logger.error("Blueprints tab error", exc_info=True)
            self._update_blueprints.emit(f"<p style='color:red'>Fehler: {e}</p>")

    # ══════════════════════════════════════════════════════════════════
    #  KILLMAILS TAB – with full details
    # ══════════════════════════════════════════════════════════════════

    def _fetch_killmails_tab(self, loop: asyncio.AbstractEventLoop, cid: int) -> None:
        try:
            kms = loop.run_until_complete(self.char_service.fetch_killmail_summaries(cid))
            if not kms:
                self._update_killmails.emit("<p>Keine Killmails.</p>")
                return

            html = f"<h3>Killmails ({len(kms)})</h3>"

            # Fetch details for first 20 killmails
            for km in kms[:20]:
                detail = loop.run_until_complete(
                    self.char_service.fetch_killmail_detail(km.killmail_id, km.killmail_hash)
                )
                if not detail:
                    html += f"<p>Killmail #{km.killmail_id}: Fehler beim Laden</p>"
                    continue

                is_loss = detail.victim and detail.victim.character_id == cid
                icon = "💀" if is_loss else "⚔️"
                time_str = _ts(detail.killmail_time)
                border_color = "{Colors.RED}" if is_loss else "{Colors.ACCENT}"

                # Resolve names for victim and all attackers
                ids_to_resolve = []
                if detail.victim and detail.victim.character_id:
                    ids_to_resolve.append(detail.victim.character_id)
                if detail.victim and detail.victim.corporation_id:
                    ids_to_resolve.append(detail.victim.corporation_id)
                for a in detail.attackers:
                    if a.character_id:
                        ids_to_resolve.append(a.character_id)
                    if a.corporation_id:
                        ids_to_resolve.append(a.corporation_id)
                km_names = loop.run_until_complete(self.name_resolver.resolve_many(ids_to_resolve)) if ids_to_resolve else {}

                victim_name = km_names.get(detail.victim.character_id, "Unknown") if detail.victim and detail.victim.character_id else "NPC/Structure"
                victim_ship = detail.victim.ship_type_name if detail.victim else "Unknown"
                victim_corp = km_names.get(detail.victim.corporation_id, "") if detail.victim and detail.victim.corporation_id else ""

                html += (
                    f"<div style='margin:8px 0;padding:10px;background:{Colors.BG_DARK};"
                    f"border-radius:6px;border-left:3px solid {border_color}'>"
                    f"<h4 style='margin:0'>{icon} {time_str} – {detail.solar_system_name}</h4>"
                    f"<p style='margin:2px 0'>Opfer: <b>{victim_name}</b>"
                )
                if victim_corp:
                    html += f" [{victim_corp}]"
                html += f" – <b>{victim_ship}</b>"
                if detail.victim:
                    html += f" – {detail.victim.damage_taken:,} Schaden"
                html += "</p>"

                # All attackers (sorted by damage)
                html += f"<details><summary style='cursor:pointer;color:{Colors.BLUE}'>⚔️ Angreifer ({len(detail.attackers)})</summary>"
                html += "<table><tr><th>Pilot</th><th>Corp</th><th>Schiff</th><th>Waffe</th><th>Schaden</th><th></th></tr>"
                for a in sorted(detail.attackers, key=lambda x: x.damage_done, reverse=True):
                    a_name = km_names.get(a.character_id, "NPC") if a.character_id else "NPC"
                    a_corp = km_names.get(a.corporation_id, "") if a.corporation_id else ""
                    fb = "🎯" if a.final_blow else ""
                    html += (
                        f"<tr><td>{a_name}</td><td>{a_corp}</td>"
                        f"<td>{a.ship_type_name}</td><td>{a.weapon_type_name}</td>"
                        f"<td>{a.damage_done:,}</td><td>{fb}</td></tr>"
                    )
                html += "</table></details>"

                # Victim items (dropped/destroyed)
                if detail.victim and detail.victim.items:
                    dropped = [i for i in detail.victim.items if i.quantity_dropped > 0]
                    destroyed = [i for i in detail.victim.items if i.quantity_destroyed > 0]

                    if dropped or destroyed:
                        html += "<details><summary style='cursor:pointer;color:{Colors.BLUE}'>📦 Items</summary>"
                        if destroyed:
                            html += "<p><b style='color:{Colors.RED}'>Zerstört:</b></p><ul>"
                            for item in sorted(destroyed, key=lambda x: x.slot_name):
                                html += f"<li>[{item.slot_name}] {item.type_name} ×{item.quantity_destroyed}</li>"
                            html += "</ul>"
                        if dropped:
                            html += "<p><b style='color:{Colors.ACCENT}'>Gedroppt:</b></p><ul>"
                            for item in sorted(dropped, key=lambda x: x.slot_name):
                                html += f"<li>[{item.slot_name}] {item.type_name} ×{item.quantity_dropped}</li>"
                            html += "</ul>"
                        html += "</details>"

                html += "</div>"

            if len(kms) > 20:
                html += f"<p><i>...und {len(kms) - 20} weitere Killmails</i></p>"

            self._update_killmails.emit(html)
        except Exception as e:
            logger.error("Killmails tab error", exc_info=True)
            self._update_killmails.emit(f"<p style='color:red'>Fehler: {e}</p>")

    # ══════════════════════════════════════════════════════════════════
    #  PI TAB – with planet names
    # ══════════════════════════════════════════════════════════════════

    def _fetch_pi_tab(self, loop: asyncio.AbstractEventLoop, cid: int) -> None:
        try:
            colonies = loop.run_until_complete(self.char_service.fetch_planetary_colonies(cid))
            if not colonies:
                self._update_pi.emit("<p>Keine PI-Kolonien.</p>")
                return

            now = datetime.now(UTC)

            # Planet type icons and colors
            planet_icons = {
                "temperate": ("🌍", "{Colors.ACCENT}"), "barren": ("🏜️", "#c0a060"),
                "oceanic": ("🌊", "#4a9eff"), "ice": ("❄️", "#b8d4e8"),
                "gas": ("☁️", "#d4a574"), "lava": ("🌋", "{Colors.RED}"),
                "storm": ("⛈️", "#6c5ce7"), "plasma": ("🔥", "#ff6b6b"),
            }

            html = f"<h3>🪐 Planetare Kolonien ({len(colonies)})</h3>"

            for c in colonies:
                icon, color = planet_icons.get(c.planet_type.lower(), ("🪐", "{Colors.TEXT_DIM}"))
                lu = _ts(c.last_update)

                # Time since last update
                update_info = ""
                if c.last_update:
                    delta = (now - c.last_update).total_seconds()
                    hours_ago = int(delta // 3600)
                    if hours_ago > 72:
                        update_info = f"<span style='color:{Colors.RED}'>⚠️ {hours_ago // 24}d ohne Update!</span>"
                    elif hours_ago > 24:
                        update_info = f"<span style='color:{Colors.ORANGE}'>⏰ {hours_ago // 24}d {hours_ago % 24}h</span>"
                    else:
                        update_info = f"<span style='color:{Colors.ACCENT}'>✓ {hours_ago}h</span>"

                # CC level progress
                level_bar = "●" * c.upgrade_level + "○" * (5 - c.upgrade_level)

                html += (
                    f"<div style='margin:8px 0;padding:10px;background:{Colors.BG_DARK};"
                    f"border-radius:6px;border-left:4px solid {color}'>"
                    f"<h4 style='margin:0'>{icon} {c.solar_system_name} – "
                    f"<span style='color:{color}'>{c.planet_type.title()}</span></h4>"
                    f"<table cellspacing='4'>"
                    f"<tr><td>CC Level:</td><td><span style='color:{Colors.ORANGE}'>{level_bar}</span> ({c.upgrade_level})</td>"
                    f"<td>Pins:</td><td>{c.num_pins}</td></tr>"
                    f"<tr><td>Letztes Update:</td><td>{lu}</td>"
                    f"<td>Status:</td><td>{update_info}</td></tr>"
                    f"</table></div>"
                )

            self._update_pi.emit(html)
        except Exception as e:
            logger.error("PI tab error", exc_info=True)
            self._update_pi.emit(f"<p style='color:red'>Fehler: {e}</p>")

    # ══════════════════════════════════════════════════════════════════
    #  CONTACTS & STANDINGS TAB – grouped by type with names
    # ══════════════════════════════════════════════════════════════════

    def _fetch_contacts_tab(self, loop: asyncio.AbstractEventLoop, cid: int) -> None:
        try:
            contacts = loop.run_until_complete(self.char_service.fetch_contacts(cid))
            standings = loop.run_until_complete(self.char_service.fetch_standings(cid))

            # Resolve ALL contact and standing IDs
            all_ids = list(set(
                [c.contact_id for c in contacts]
                + [s.from_id for s in standings]
            ))
            names = loop.run_until_complete(self.name_resolver.resolve_many(all_ids)) if all_ids else {}

            def _standing_style(standing: float) -> tuple[str, str, str]:
                """Return (color, icon, label) for EVE standing value."""
                if standing >= 10.0:
                    return "#1f69ff", "💙", "Exzellent"
                elif standing >= 5.0:
                    return "#4a9eff", "🔵", "Gut"
                elif standing > 0.0:
                    return "#7ab8ff", "🔹", "Positiv"
                elif standing == 0.0:
                    return "{Colors.TEXT_DIM}", "⬜", "Neutral"
                elif standing > -5.0:
                    return "{Colors.ORANGE}", "🔸", "Negativ"
                elif standing > -10.0:
                    return "{Colors.RED}", "🔴", "Schlecht"
                else:
                    return "#c0392b", "💔", "Feindlich"

            def _standing_bar(standing: float) -> str:
                """HTML standing bar from -10 to +10."""
                pct = int(50 + (standing / 10.0) * 50)
                pct = max(2, min(98, pct))
                color, _, _ = _standing_style(standing)
                return (
                    f"<div style='display:inline-block;width:80px;height:12px;"
                    f"background:linear-gradient(90deg,{Colors.RED} 0%,{Colors.TEXT_DIM} 50%,#1f69ff 100%);"
                    f"border-radius:6px;position:relative;border:1px solid {Colors.BORDER}'>"
                    f"<div style='position:absolute;left:{pct}%;top:-1px;width:3px;height:14px;"
                    f"background:{color};border-radius:1px'></div></div>"
                )

            html = ""

            # Contacts grouped by type
            if contacts:
                by_type: dict[str, list] = {}
                for c in contacts:
                    by_type.setdefault(c.contact_type, []).append(c)

                type_icons = {"character": "👤", "corporation": "🏢", "alliance": "⚔️", "faction": "🏛️"}
                html += f"<h3>Kontakte ({len(contacts)})</h3>"
                for ct in sorted(by_type):
                    ct_contacts = sorted(by_type[ct], key=lambda x: x.standing, reverse=True)
                    icon = type_icons.get(ct, "📇")
                    html += f"<h4>{icon} {ct.title()} ({len(ct_contacts)})</h4><table>"
                    html += "<tr><th>Name</th><th>Standing</th><th></th><th></th></tr>"
                    for c in ct_contacts:
                        color, st_icon, st_label = _standing_style(c.standing)
                        cname = names.get(c.contact_id, f"#{c.contact_id}")
                        bar = _standing_bar(c.standing)
                        watched = " 👁️" if c.is_watched else ""
                        blocked = " 🚫" if c.is_blocked else ""
                        html += (
                            f"<tr><td>{cname}{watched}{blocked}</td>"
                            f"<td style='color:{color}'>{st_icon} {c.standing:+.1f}</td>"
                            f"<td>{bar}</td>"
                            f"<td style='color:{Colors.TEXT_DIM};font-size:0.85em'>{st_label}</td></tr>"
                        )
                    html += "</table>"

            # NPC Standings grouped by type
            if standings:
                by_type_s: dict[str, list] = {}
                for s in standings:
                    by_type_s.setdefault(s.from_type, []).append(s)

                type_icons_s = {"agent": "🕵️", "npc_corp": "🏢", "faction": "🏛️"}
                html += f"<h3>NPC Standings ({len(standings)})</h3>"
                for ft in sorted(by_type_s):
                    ft_standings = sorted(by_type_s[ft], key=lambda x: x.standing, reverse=True)
                    icon = type_icons_s.get(ft, "📊")
                    html += f"<h4>{icon} {ft.replace('_', ' ').title()} ({len(ft_standings)})</h4><table>"
                    html += "<tr><th>Name</th><th>Standing</th><th></th><th></th></tr>"
                    for s in ft_standings:
                        color, st_icon, st_label = _standing_style(s.standing)
                        sname = names.get(s.from_id, f"#{s.from_id}")
                        bar = _standing_bar(s.standing)
                        html += (
                            f"<tr><td>{sname}</td>"
                            f"<td style='color:{color}'>{st_icon} {s.standing:+.2f}</td>"
                            f"<td>{bar}</td>"
                            f"<td style='color:{Colors.TEXT_DIM};font-size:0.85em'>{st_label}</td></tr>"
                        )
                    html += "</table>"

            if not contacts and not standings:
                html = "<p>Keine Kontakte oder Standings.</p>"

            self._update_contacts.emit(html)
        except Exception as e:
            logger.error("Contacts tab error", exc_info=True)
            self._update_contacts.emit(f"<p style='color:red'>Fehler: {e}</p>")

    # ══════════════════════════════════════════════════════════════════
    #  NOTIFICATIONS TAB – with sender names
    # ══════════════════════════════════════════════════════════════════

    def _fetch_notifications_tab(self, loop: asyncio.AbstractEventLoop, cid: int) -> None:
        try:
            notifs = loop.run_until_complete(self.char_service.fetch_notifications(cid))
            if not notifs:
                self._update_notifications.emit("<p>Keine Benachrichtigungen.</p>")
                return

            # Resolve sender IDs
            sender_ids = list(set(n.sender_id for n in notifs if n.sender_id))
            if sender_ids:
                sender_names = loop.run_until_complete(self.name_resolver.resolve_many(sender_ids))
            else:
                sender_names = {}

            # Group by category
            by_category: dict[str, list] = {}
            for n in notifs:
                cat = get_notification_category(n.type)
                by_category.setdefault(cat, []).append(n)

            html = f"<h3>Benachrichtigungen ({len(notifs)})</h3>"

            # Show ungrouped (chronological) with parsed type names
            for cat_name in sorted(by_category.keys()):
                cat_notifs = by_category[cat_name]
                html += f"<h4>{cat_name} ({len(cat_notifs)})</h4>"

                for n in cat_notifs:
                    ts = _ts(n.timestamp)
                    icon, desc = parse_notification_type(n.type)
                    sender = sender_names.get(n.sender_id, n.sender_type)
                    read_style = "color:{Colors.TEXT_DIM}" if n.is_read else "color:{Colors.TEXT_HEADING};font-weight:bold"
                    bg = "{Colors.BG_DARKEST}" if n.is_read else "{Colors.BG_DARK}"

                    html += (
                        f"<div style='margin:3px 0;padding:6px;background:{bg};"
                        f"border-radius:4px;{read_style}'>"
                        f"{icon} <b>{desc}</b> "
                        f"<span style='color:{Colors.TEXT_DIM}'>| {sender} | {ts}</span>"
                    )

                    # Parse notification text for extra details (YAML-like format)
                    if n.text and not n.is_read:
                        # Show raw text for unread important notifications
                        clean_text = n.text[:200].replace("\n", " | ").strip()
                        if clean_text:
                            html += f"<br><span style='color:{Colors.TEXT_DIM};font-size:0.9em'>{clean_text}</span>"

                    html += "</div>"

            self._update_notifications.emit(html)
        except Exception as e:
            logger.error("Notifications tab error", exc_info=True)
            self._update_notifications.emit(f"<p style='color:red'>Fehler: {e}</p>")

    # ══════════════════════════════════════════════════════════════════
    #  CALENDAR TAB
    # ══════════════════════════════════════════════════════════════════

    def _fetch_calendar_tab(self, loop: asyncio.AbstractEventLoop, cid: int) -> None:
        try:
            events = loop.run_until_complete(self.char_service.fetch_calendar_events(cid))
            if not events:
                self._update_calendar.emit("<p>Keine anstehenden Events.</p>")
                return

            html = f"<h3>Kalender ({len(events)} Events)</h3><table>"
            html += "<tr><th>Datum</th><th>Titel</th><th>Antwort</th></tr>"
            for ev in events:
                ts = _ts(ev.event_date)
                response_icon = {"accepted": "✓", "declined": "✗", "tentative": "?", "not_responded": "–"}.get(
                    ev.event_response, "–"
                )
                html += f"<tr><td>{ts}</td><td>{ev.title}</td><td>{response_icon} {ev.event_response}</td></tr>"
            html += "</table>"

            self._update_calendar.emit(html)
        except Exception as e:
            logger.error("Calendar tab error", exc_info=True)
            self._update_calendar.emit(f"<p style='color:red'>Fehler: {e}</p>")

    # ══════════════════════════════════════════════════════════════════
    #  RESEARCH TAB
    # ══════════════════════════════════════════════════════════════════

    def _fetch_research_tab(self, loop: asyncio.AbstractEventLoop, cid: int) -> None:
        try:
            agents = loop.run_until_complete(self.char_service.fetch_research_agents(cid))
            if not agents:
                self._update_research.emit("<p>Keine Research Agents.</p>")
                return

            # Resolve agent names
            agent_ids = [a.agent_id for a in agents]
            agent_names = loop.run_until_complete(self.name_resolver.resolve_many(agent_ids)) if agent_ids else {}

            html = f"<h3>Research Agents ({len(agents)})</h3><table>"
            html += "<tr><th>Agent</th><th>Skill</th><th>RP/Tag</th><th>RP Gesamt</th><th>Seit</th></tr>"
            for a in agents:
                aname = agent_names.get(a.agent_id, f"Agent #{a.agent_id}")
                since = _ts(a.started_at, "%Y-%m-%d")
                # Calculate accumulated RP
                total_rp = a.remainder_points
                if a.started_at:
                    days = (datetime.now(UTC) - a.started_at).total_seconds() / 86400
                    total_rp += days * a.points_per_day
                html += (
                    f"<tr><td>{aname}</td><td>{a.skill_type_name}</td>"
                    f"<td>{a.points_per_day:.2f}</td><td>{total_rp:,.0f}</td><td>{since}</td></tr>"
                )
            html += "</table>"

            self._update_research.emit(html)
        except Exception as e:
            logger.error("Research tab error", exc_info=True)
            self._update_research.emit(f"<p style='color:red'>Fehler: {e}</p>")

    # ══════════════════════════════════════════════════════════════════
    #  MEDALS TAB
    # ══════════════════════════════════════════════════════════════════

    def _fetch_medals_tab(self, loop: asyncio.AbstractEventLoop, cid: int) -> None:
        try:
            medals = loop.run_until_complete(self.char_service.fetch_medals(cid))
            if not medals:
                self._update_medals.emit("<p>Keine Medaillen.</p>")
                return

            # Resolve corporation IDs
            corp_ids = list(set(m.corporation_id for m in medals if m.corporation_id))
            corp_names = loop.run_until_complete(self.name_resolver.resolve_many(corp_ids)) if corp_ids else {}

            html = f"<h3>Medaillen ({len(medals)})</h3>"
            for m in medals:
                dt = _ts(m.date, "%Y-%m-%d")
                corp_name = corp_names.get(m.corporation_id, f"Corp #{m.corporation_id}")
                html += (
                    f"<div style='margin:8px 0;padding:8px;background:{Colors.BG_DARK};border-radius:4px'>"
                    f"<b>🏅 {m.title}</b> ({m.status})<br>"
                    f"Von: {corp_name} | {dt}<br>"
                )
                if m.description:
                    html += f"<p>{m.description}</p>"
                if m.reason:
                    html += f"<p><i>Grund: {m.reason}</i></p>"
                html += "</div>"

            self._update_medals.emit(html)
        except Exception as e:
            logger.error("Medals tab error", exc_info=True)
            self._update_medals.emit(f"<p style='color:red'>Fehler: {e}</p>")

    # ══════════════════════════════════════════════════════════════════
    #  CLONES & IMPLANTS TAB
    # ══════════════════════════════════════════════════════════════════

    def _fetch_clones_tab(self, loop: asyncio.AbstractEventLoop, cid: int) -> None:
        try:
            clones = loop.run_until_complete(self.char_service.fetch_clones(cid))
            implant_names = loop.run_until_complete(self.char_service.fetch_implants(cid))

            # Also fetch raw implant IDs for the Implant Calculator
            try:
                implant_ids = loop.run_until_complete(
                    self.char_service.fetch_implant_ids(cid)
                )
                # Fetch character attributes for implant calculator
                attrs_raw = loop.run_until_complete(self.char_service.fetch_attributes(cid))
                base_attrs = {
                    "intelligence": attrs_raw.get("intelligence", 17),
                    "memory": attrs_raw.get("memory", 17),
                    "perception": attrs_raw.get("perception", 17),
                    "willpower": attrs_raw.get("willpower", 17),
                    "charisma": attrs_raw.get("charisma", 17),
                }
                self._update_implant_calc.emit(implant_ids, base_attrs)
            except Exception:
                logger.debug("Could not update implant calculator", exc_info=True)

            html = "<h3>🧬 Klone &amp; Implantate</h3>"

            # Active implants
            if implant_names:
                html += "<h4>💉 Aktive Implantate</h4><table>"
                html += "<tr><th>#</th><th>Implantat</th></tr>"

                # Group by slot (implant names often contain slot info)
                for idx, name in enumerate(implant_names, 1):
                    # Determine slot color based on type
                    if any(a in name.lower() for a in ["intelligence", "memory", "perception",
                                                        "willpower", "charisma", "neural",
                                                        "cybernetic", "social"]):
                        slot_color = "{Colors.BLUE}"  # Attribute implants
                    elif any(a in name.lower() for a in ["hardwiring", "slot"]):
                        slot_color = "{Colors.ORANGE}"  # Hardwiring
                    else:
                        slot_color = "{Colors.TEXT_HEADING}"

                    html += (
                        f"<tr><td style='color:{Colors.TEXT_DIM}'>{idx}</td>"
                        f"<td style='color:{slot_color}'>{name}</td></tr>"
                    )
                html += "</table>"
            else:
                html += "<p style='color:{Colors.TEXT_DIM}'>Keine aktiven Implantate.</p>"

            # Jump Clones
            if clones:
                html += f"<h4>🔄 Jump Clones ({len(clones)})</h4>"

                # Resolve location IDs
                loc_ids = list(set(c.location_id for c in clones if c.location_id))
                loc_names = loop.run_until_complete(
                    self.name_resolver.resolve_many(loc_ids)
                ) if loc_ids else {}

                for clone in clones:
                    loc_name = loc_names.get(clone.location_id,
                                             clone.location_name or f"Location #{clone.location_id}")

                    html += (
                        f"<div style='margin:6px 0;padding:10px;background:{Colors.BG_DARK};"
                        f"border-radius:6px;border-left:3px solid #8957e5'>"
                        f"<b>📍 {loc_name}</b>"
                        f"<span style='color:{Colors.TEXT_DIM};margin-left:12px'>{clone.location_type}</span>"
                    )

                    # Clone implants
                    if clone.implants:
                        imp_names = []
                        for imp_id in clone.implants:
                            t = self.sde.get_type_name(imp_id)
                            imp_names.append(t if t else f"Type #{imp_id}")
                        html += "<ul style='margin:4px 0'>"
                        for iname in imp_names:
                            html += f"<li style='color:{Colors.TEXT_HEADING}'>{iname}</li>"
                        html += "</ul>"
                    else:
                        html += "<p style='color:{Colors.TEXT_DIM};margin:2px 0'>Keine Implantate</p>"

                    html += "</div>"
            else:
                html += "<p style='color:{Colors.TEXT_DIM}'>Keine Jump Clones.</p>"

            self._update_clones.emit(html)
        except Exception as e:
            logger.error("Clones tab error", exc_info=True)
            self._update_clones.emit(f"<p style='color:red'>Fehler: {e}</p>")

    # ══════════════════════════════════════════════════════════════════
    #  BOOKMARKS TAB
    # ══════════════════════════════════════════════════════════════════

    def _fetch_bookmarks_tab(self, loop: asyncio.AbstractEventLoop, cid: int) -> None:
        """Bookmarks ESI endpoints were removed by CCP.

        Show an informational message instead of fetching data.
        If cached bookmarks exist in the DB, display them.
        """
        try:
            # Check for cached bookmarks in local DB
            cached = self.db.conn.execute(
                "SELECT * FROM bookmarks WHERE character_id = ? ORDER BY label",
                (cid,),
            ).fetchall()

            html = "<h3>🔖 Lesezeichen</h3>"
            html += (
                "<div style='background:#3d2b1f; border:1px solid #b8860b; "
                "border-radius:6px; padding:12px; margin:8px 0;'>"
                "<p style='color:#ffd700; font-weight:bold;'>⚠️ API entfernt</p>"
                "<p style='color:#deb887;'>CCP hat die Bookmarks-ESI-Endpoints "
                "entfernt. Neue Lesezeichen können nicht mehr über die API "
                "abgerufen werden.</p>"
                "<p style='color:{Colors.TEXT_DIM}; font-size:0.9em;'>Die Scopes "
                "<code>esi-bookmarks.read_character_bookmarks.v1</code> und "
                "<code>esi-bookmarks.read_corporation_bookmarks.v1</code> "
                "existieren nicht mehr im ESI.</p>"
                "</div>"
            )

            if cached:
                html += f"<h4>📋 Gespeicherte Lesezeichen ({len(cached)})</h4>"
                html += "<p style='color:{Colors.TEXT_DIM}'>Zuletzt gecachte Daten:</p>"
                html += "<table><tr><th>Label</th><th>Notizen</th><th>Erstellt</th></tr>"
                for bm in cached:
                    label = bm["label"] or "-"
                    notes = bm["notes"] or "-"
                    if len(notes) > 80:
                        notes = notes[:80] + "..."
                    created = bm["created"] or "-"
                    html += (
                        f"<tr><td>🔖 <b>{label}</b></td>"
                        f"<td style='color:{Colors.TEXT_DIM}'>{notes}</td>"
                        f"<td>{created}</td></tr>"
                    )
                html += "</table>"
            else:
                html += "<p style='color:{Colors.TEXT_DIM}'>Keine gespeicherten Lesezeichen im Cache.</p>"

            self._update_bookmarks.emit(html)
        except Exception as e:
            logger.error("Bookmarks tab error", exc_info=True)
            self._update_bookmarks.emit(f"<p style='color:red'>Fehler: {e}</p>")

    # ══════════════════════════════════════════════════════════════════
    #  LOYALTY POINTS TAB
    # ══════════════════════════════════════════════════════════════════

    def _fetch_loyalty_tab(self, loop: asyncio.AbstractEventLoop, cid: int) -> None:
        try:
            lp_entries = loop.run_until_complete(self.char_service.fetch_loyalty_points(cid))
            if not lp_entries:
                self._update_loyalty.emit("<p>Keine Loyalty Points.</p>")
                return

            # Resolve corporation names
            corp_ids = [lp.corporation_id for lp in lp_entries]
            corp_names = loop.run_until_complete(
                self.name_resolver.resolve_many(corp_ids)
            ) if corp_ids else {}

            total_lp = sum(lp.loyalty_points for lp in lp_entries)

            html = f"<h3>🏆 Loyalty Points ({total_lp:,} LP gesamt)</h3>"

            # Sort by LP amount, highest first
            sorted_lp = sorted(lp_entries, key=lambda x: x.loyalty_points, reverse=True)

            # Find max for bar scaling
            max_lp = max(lp.loyalty_points for lp in sorted_lp) if sorted_lp else 1

            html += "<table style='width:100%'>"
            html += "<tr><th>Corporation</th><th>LP</th><th>Anteil</th></tr>"

            for lp in sorted_lp:
                name = corp_names.get(lp.corporation_id, f"Corp #{lp.corporation_id}")
                bar_pct = int(100 * lp.loyalty_points / max_lp) if max_lp > 0 else 0
                share_pct = (100 * lp.loyalty_points / total_lp) if total_lp > 0 else 0

                # Color gradient based on amount
                if lp.loyalty_points >= 100000:
                    color = "{Colors.ACCENT}"
                elif lp.loyalty_points >= 10000:
                    color = "{Colors.BLUE}"
                elif lp.loyalty_points >= 1000:
                    color = "{Colors.ORANGE}"
                else:
                    color = "{Colors.TEXT_DIM}"

                bar = (
                    f"<div style='display:inline-block;width:200px;height:14px;"
                    f"background:{Colors.BG_DARK};border:1px solid {Colors.BORDER};border-radius:3px'>"
                    f"<div style='width:{bar_pct}%;height:100%;background:{color};"
                    f"border-radius:2px'></div></div>"
                    f" <span style='color:{Colors.TEXT_DIM};font-size:0.85em'>{share_pct:.1f}%</span>"
                )

                html += (
                    f"<tr><td>🏢 <b>{name}</b></td>"
                    f"<td style='color:{color};text-align:right'><b>{lp.loyalty_points:,}</b></td>"
                    f"<td>{bar}</td></tr>"
                )

            html += "</table>"

            self._update_loyalty.emit(html)
        except Exception as e:
            logger.error("Loyalty tab error", exc_info=True)
            self._update_loyalty.emit(f"<p style='color:red'>Fehler: {e}</p>")

    # ══════════════════════════════════════════════════════════════════
    #  MINING LEDGER TAB
    # ══════════════════════════════════════════════════════════════════

    def _fetch_mining_tab(self, loop: asyncio.AbstractEventLoop, cid: int) -> None:
        try:
            entries = loop.run_until_complete(self.char_service.fetch_mining_ledger(cid))
            if not entries:
                self._update_mining.emit("<p>Kein Mining-Ledger (letzte 30 Tage).</p>")
                return

            # Aggregate by ore type
            by_type: dict[str, int] = {}
            by_system: dict[str, int] = {}
            by_date: dict[str, int] = {}
            total_volume = 0

            for e in entries:
                type_name = e.type_name or self.sde.get_type_name(e.type_id)
                system_name = e.solar_system_name or self.sde.get_system_name(e.solar_system_id)
                by_type[type_name] = by_type.get(type_name, 0) + e.quantity
                by_system[system_name] = by_system.get(system_name, 0) + e.quantity
                by_date[e.date] = by_date.get(e.date, 0) + e.quantity
                total_volume += e.quantity

            # Estimate ISK value from SDE base_price
            total_value = 0.0
            type_values: dict[str, float] = {}
            for e in entries:
                t = self.sde.get_type(e.type_id)
                if t and t.get("base_price"):
                    val = t["base_price"] * e.quantity
                    type_name = e.type_name or self.sde.get_type_name(e.type_id)
                    type_values[type_name] = type_values.get(type_name, 0) + val
                    total_value += val

            html = (
                f"<h3>⛏️ Mining Ledger ({len(entries)} Einträge, "
                f"letzte 30 Tage)</h3>"
                f"<table cellspacing='6'>"
                f"<tr><td>📦 Gesamt-Volumen:</td><td><b>{total_volume:,}</b> Einheiten</td>"
                f"<td>💰 ~Basiswert:</td><td style='color:{Colors.ACCENT}'><b>{total_value:,.0f} ISK</b></td>"
                f"<td>📅 Aktive Tage:</td><td><b>{len(by_date)}</b></td></tr>"
                f"</table>"
            )

            # Mining activity sparkline (by date)
            if by_date:
                sorted_dates = sorted(by_date.keys())
                html += "<div style='margin:8px 0;padding:8px;background:{Colors.BG_DARKEST};border-radius:6px'>"
                html += "<p style='margin:0 0 4px 0;color:{Colors.TEXT_DIM};font-size:0.85em'>Tägliches Mining-Volumen</p>"
                html += "<div style='display:flex;align-items:flex-end;height:50px;gap:2px'>"
                max_daily = max(by_date.values())
                for d in sorted_dates:
                    pct = max(3, int(100 * by_date[d] / max_daily)) if max_daily > 0 else 3
                    html += (
                        f"<div style='flex:1;height:{pct}%;background:{Colors.ORANGE};"
                        f"border-radius:1px' title='{d}: {by_date[d]:,}'></div>"
                    )
                html += "</div>"
                html += (
                    f"<div style='display:flex;justify-content:space-between;color:{Colors.TEXT_DIM};font-size:0.75em'>"
                    f"<span>{sorted_dates[0]}</span><span>{sorted_dates[-1]}</span></div>"
                )
                html += "</div>"

            # By ore type (sorted by quantity)
            html += "<h4>🪨 Nach Erz-Typ</h4><table style='width:100%'>"
            html += "<tr><th>Erz</th><th>Menge</th><th>~ISK</th><th></th></tr>"
            max_qty = max(by_type.values()) if by_type else 1
            for type_name in sorted(by_type, key=by_type.get, reverse=True):
                qty = by_type[type_name]
                val = type_values.get(type_name, 0)
                bar_pct = int(100 * qty / max_qty) if max_qty > 0 else 0
                val_str = f"{val:,.0f}" if val > 0 else "-"
                bar = (
                    f"<div style='display:inline-block;width:120px;height:12px;"
                    f"background:{Colors.BG_DARK};border:1px solid {Colors.BORDER};border-radius:3px'>"
                    f"<div style='width:{bar_pct}%;height:100%;background:{Colors.ORANGE};"
                    f"border-radius:2px'></div></div>"
                )
                html += (
                    f"<tr><td>⛏️ <b>{type_name}</b></td>"
                    f"<td style='text-align:right'>{qty:,}</td>"
                    f"<td style='text-align:right;color:{Colors.ACCENT}'>{val_str}</td>"
                    f"<td>{bar}</td></tr>"
                )
            html += "</table>"

            # By system
            html += "<h4>🌐 Nach System</h4><table>"
            html += "<tr><th>System</th><th>Menge</th></tr>"
            for sys_name in sorted(by_system, key=by_system.get, reverse=True):
                html += f"<tr><td>📍 {sys_name}</td><td style='text-align:right'>{by_system[sys_name]:,}</td></tr>"
            html += "</table>"

            self._update_mining.emit(html)

            # Feed trade advisor with mining data
            mining_dicts = [
                {
                    "type_id": e.type_id,
                    "type_name": e.type_name or self.sde.get_type_name(e.type_id),
                    "quantity": e.quantity,
                }
                for e in entries
            ]
            self._update_trade_advisor_mining.emit(mining_dicts)
        except Exception as e:
            logger.error("Mining tab error", exc_info=True)
            self._update_mining.emit(f"<p style='color:red'>Fehler: {e}</p>")

    # ══════════════════════════════════════════════════════════════════
    #  FACTIONAL WARFARE TAB
    # ══════════════════════════════════════════════════════════════════

    def _fetch_fw_tab(self, loop: asyncio.AbstractEventLoop, cid: int) -> None:
        try:
            stats = loop.run_until_complete(self.char_service.fetch_fw_stats(cid))
            if not stats:
                self._update_fw.emit("<p>Nicht in Factional Warfare aktiv.</p>")
                return

            # Resolve faction name
            faction_id = stats.get("faction_id", 0)
            faction_names = loop.run_until_complete(
                self.name_resolver.resolve_many([faction_id])
            ) if faction_id else {}
            faction_name = faction_names.get(faction_id, f"Faction #{faction_id}")

            # Faction colors
            faction_colors = {
                500001: ("#d4a017", "☀️"),   # Caldari State
                500002: ("#4a9eff", "🔵"),   # Minmatar Republic
                500003: ("{Colors.ACCENT}", "🌿"),   # Amarr Empire
                500004: ("{Colors.RED}", "🔴"),   # Gallente Federation
            }
            color, icon = faction_colors.get(faction_id, ("{Colors.TEXT_DIM}", "⚔️"))

            enlisted_date = stats.get("enlisted_on", "")
            if enlisted_date:
                enlisted_date = enlisted_date[:10]

            html = (
                f"<h3>{icon} Factional Warfare</h3>"
                f"<div style='margin:8px 0;padding:12px;background:{Colors.BG_DARK};"
                f"border-radius:6px;border-left:4px solid {color}'>"
                f"<table cellspacing='6'>"
                f"<tr><td>Fraktion:</td><td style='color:{color}'><b>{faction_name}</b></td></tr>"
                f"<tr><td>Beigetreten:</td><td>{enlisted_date}</td></tr>"
            )

            # Current rank
            current_rank = stats.get("current_rank", 0)
            highest_rank = stats.get("highest_rank", 0)
            if current_rank or highest_rank:
                html += (
                    f"<tr><td>Aktueller Rang:</td><td><b>{current_rank}</b></td></tr>"
                    f"<tr><td>Höchster Rang:</td><td>{highest_rank}</td></tr>"
                )

            html += "</table></div>"

            # Kill statistics – ESI returns kills.{yesterday,last_week,total} as flat ints
            kills = stats.get("kills", {})
            vp = stats.get("victory_points", {})
            if kills or vp:
                k_yesterday = kills.get("yesterday", 0) if isinstance(kills, dict) else 0
                k_last = kills.get("last_week", 0) if isinstance(kills, dict) else 0
                k_total = kills.get("total", 0) if isinstance(kills, dict) else 0
                vp_yesterday = vp.get("yesterday", 0) if isinstance(vp, dict) else 0
                vp_last = vp.get("last_week", 0) if isinstance(vp, dict) else 0
                vp_total = vp.get("total", 0) if isinstance(vp, dict) else 0

                html += (
                    "<h4>⚔️ Kills &amp; Victory Points</h4><table>"
                    "<tr><th>Zeitraum</th><th>Kills</th><th>Victory Points</th></tr>"
                    f"<tr><td>Gestern</td>"
                    f"<td style='color:{Colors.ACCENT}'>{k_yesterday:,}</td>"
                    f"<td>{vp_yesterday:,}</td></tr>"
                    f"<tr><td>Letzte Woche</td>"
                    f"<td style='color:{Colors.ACCENT}'>{k_last:,}</td>"
                    f"<td>{vp_last:,}</td></tr>"
                    f"<tr><td><b>Gesamt</b></td>"
                    f"<td style='color:{Colors.ACCENT}'><b>{k_total:,}</b></td>"
                    f"<td><b>{vp_total:,}</b></td></tr>"
                    "</table>"
                )

            self._update_fw.emit(html)
        except Exception as e:
            logger.error("FW tab error", exc_info=True)
            self._update_fw.emit(f"<p style='color:red'>Fehler: {e}</p>")

    # ══════════════════════════════════════════════════════════════════
    #  CHARACTER PORTRAIT
    # ══════════════════════════════════════════════════════════════════

    def _fetch_portrait(self, loop: asyncio.AbstractEventLoop, cid: int) -> None:
        """Fetch and display character portrait."""
        try:
            url = loop.run_until_complete(self.char_service.fetch_portrait_url(cid))
            if not url:
                return
            import httpx
            async def _download():
                async with httpx.AsyncClient() as client:
                    resp = await client.get(url)
                    return resp.content
            img_data = loop.run_until_complete(_download())
            pixmap = QPixmap()
            pixmap.loadFromData(QByteArray(img_data))
            if not pixmap.isNull():
                self._update_portrait.emit(pixmap.scaled(128, 128, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        except Exception:
            logger.error("Portrait fetch error", exc_info=True)

    def _on_portrait_loaded(self, pixmap: QPixmap) -> None:
        """Update portrait label on main thread."""
        self.portrait_label.setPixmap(pixmap)

    # ══════════════════════════════════════════════════════════════════
    #  SERVER STATUS
    # ══════════════════════════════════════════════════════════════════

    def _update_server_status(self) -> None:
        """Fetch and display server status."""
        import threading

        def _fetch_status() -> None:
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                status = loop.run_until_complete(self.status_api.get_server_status())
                players = status.get("players", 0)
                version = status.get("server_version", "?")
                self._update_server_status_text.emit(
                    f"🟢 Tranquility: {players:,} Spieler online | v{version}"
                )
            except Exception:
                self._update_server_status_text.emit("🔴 Server nicht erreichbar")

        thread = threading.Thread(target=_fetch_status, daemon=True)
        thread.start()

    # ══════════════════════════════════════════════════════════════════
    #  REFRESH
    # ══════════════════════════════════════════════════════════════════

    def refresh_data(self) -> None:
        """Periodic data refresh."""
        self._update_server_status()
        item = self.char_list.currentItem()
        if item:
            character_id = item.data(Qt.ItemDataRole.UserRole)
            self._fetch_character_data(character_id)

    # ══════════════════════════════════════════════════════════════════
    #  CSV EXPORT
    # ══════════════════════════════════════════════════════════════════

    def _on_export_csv(self) -> None:
        """Export the current tab's data as CSV."""
        import csv
        import re

        from PySide6.QtWidgets import QFileDialog

        # Get the current tab label
        current_idx = self.tabs.currentIndex()
        tab_name = self.tabs.tabText(current_idx)

        # Find the QLabel in the current tab
        widget = self.tabs.currentWidget()
        if not widget:
            return
        # The label is inside a QScrollArea
        label = None
        from PySide6.QtWidgets import QScrollArea as _SA
        if isinstance(widget, _SA) and widget.widget() and isinstance(widget.widget(), QLabel):
            label = widget.widget()
        if not label:
            QMessageBox.information(self, "Export", "Dieser Tab kann nicht exportiert werden.")
            return

        html = label.text()
        if not html or "<table" not in html.lower():
            QMessageBox.information(self, "Export", "Keine Tabellendaten zum Exportieren.")
            return

        # Parse HTML tables into rows
        rows: list[list[str]] = []
        # Find all tables
        tables = re.findall(r"<table[^>]*>(.*?)</table>", html, re.DOTALL | re.IGNORECASE)
        for table_html in tables:
            # Extract rows
            tr_matches = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.DOTALL | re.IGNORECASE)
            for tr_html in tr_matches:
                cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr_html, re.DOTALL | re.IGNORECASE)
                # Strip HTML tags from cell content
                clean_cells = [re.sub(r"<[^>]+>", "", cell).strip() for cell in cells]
                if clean_cells:
                    rows.append(clean_cells)

        if not rows:
            QMessageBox.information(self, "Export", "Keine Tabellendaten gefunden.")
            return

        # Ask user for filename
        default_name = f"PyMon_{tab_name.replace(' ', '_')}_{__import__('datetime').datetime.now():%Y%m%d_%H%M%S}.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, f"'{tab_name}' exportieren", default_name, "CSV-Dateien (*.csv);;Alle Dateien (*.*)"
        )
        if not path:
            return

        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f, delimiter=";")
                for row in rows:
                    writer.writerow(row)
            self.status_bar.showMessage(f"✓ {len(rows)} Zeilen nach {path} exportiert", 5000)
        except Exception as e:
            QMessageBox.critical(self, "Export-Fehler", str(e))

    # ══════════════════════════════════════════════════════════════════
    #  ICS EXPORT / CLOUD SYNC / AUTO-UPDATE
    # ══════════════════════════════════════════════════════════════════

    def _get_current_char_name(self) -> str:
        """Return the name of the currently selected character."""
        item = self.char_list.currentItem()
        if item:
            return item.text()
        return "Unbekannt"

    def _on_export_ics(self) -> None:
        """Export the current skill queue as ICS calendar file."""
        if not self._current_character_id:
            QMessageBox.information(self, "ICS Export", "Kein Charakter ausgewählt.")
            return

        char_name = self._get_current_char_name()
        # Get skill queue from the cached data
        try:
            import asyncio as _aio
            loop = _aio.new_event_loop()
            queue = loop.run_until_complete(
                self.char_service.fetch_skill_queue(self._current_character_id)
            )
            loop.close()
        except Exception:
            queue = []

        if not queue:
            QMessageBox.information(self, "ICS Export", "Skill Queue ist leer.")
            return

        # Build type_names mapping
        type_names = {}
        for e in queue:
            sid = getattr(e, "skill_id", 0) or getattr(e, "type_id", 0)
            if sid:
                type_names[sid] = self.sde.get_type_name(sid)

        # Convert queue to list of dicts
        queue_dicts = []
        for e in queue:
            queue_dicts.append({
                "skill_id": getattr(e, "skill_id", 0),
                "finished_level": getattr(e, "finished_level", 0),
                "start_date": getattr(e, "start_date", None),
                "finish_date": getattr(e, "finish_date", None),
            })

        default_name = f"PyMon_{char_name}_SkillQueue.ics"
        path, _ = QFileDialog.getSaveFileName(
            self, "Skill Queue als ICS exportieren", default_name,
            "iCalendar (*.ics);;Alle Dateien (*.*)"
        )
        if not path:
            return

        ok, msg = export_ics_file(path, char_name, queue_dicts, type_names)
        if ok:
            QMessageBox.information(self, "ICS Export", msg)
        else:
            QMessageBox.critical(self, "ICS Export", msg)

    def _on_cloud_export(self) -> None:
        """Export data to cloud sync folder."""
        if not self._cloud_sync.is_configured:
            QMessageBox.information(
                self, "Cloud Sync",
                "Cloud-Ordner nicht konfiguriert.\n"
                "Bitte unter Einstellungen → Cloud Sync einen Ordner auswählen."
            )
            return
        ok, msg = self._cloud_sync.export_to_cloud()
        if ok:
            QMessageBox.information(self, "Cloud Export", msg)
        else:
            QMessageBox.critical(self, "Cloud Export", msg)

    def _on_cloud_import(self) -> None:
        """Import data from cloud sync folder."""
        if not self._cloud_sync.is_configured:
            QMessageBox.information(
                self, "Cloud Sync",
                "Cloud-Ordner nicht konfiguriert.\n"
                "Bitte unter Einstellungen → Cloud Sync einen Ordner auswählen."
            )
            return
        reply = QMessageBox.question(
            self, "Cloud Import",
            "Aktuelle Daten werden mit dem Cloud-Backup überschrieben.\n"
            "Fortfahren?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        ok, msg = self._cloud_sync.import_from_cloud()
        if ok:
            QMessageBox.information(self, "Cloud Import", msg)
        else:
            QMessageBox.critical(self, "Cloud Import", msg)

    def _check_for_updates(self) -> None:
        """Check for updates from GitHub releases."""
        self._update_thread = UpdateCheckThread(parent=self)
        self._update_thread.update_available.connect(self._on_update_available)
        self._update_thread.start()

    def _on_update_available(self, version: str, url: str) -> None:
        """Show update dialog when a new version is available."""
        dialog = UpdateDialog(version, url, self)
        dialog.exec()

    # ══════════════════════════════════════════════════════════════════
    #  DIALOGS
    # ══════════════════════════════════════════════════════════════════

    # ══════════════════════════════════════════════════════════════════
    #  WINDOW LAYOUT PERSISTENCE
    # ══════════════════════════════════════════════════════════════════

    def _save_window_layout(self) -> None:
        """Save current window arrangement for next session."""
        try:
            layout = WindowLayout()

            # Main window geometry
            g = self.geometry()
            layout.main_geometry = {
                "x": g.x(), "y": g.y(),
                "w": g.width(), "h": g.height(),
            }
            layout.main_maximized = self.isMaximized()

            # Active tab
            layout.active_tab = self.tabs.currentIndex()
            layout.active_tab_name = self.tabs.current_tab_title()

            # Splitter sizes
            splitter = self.centralWidget()
            if hasattr(splitter, "sizes"):
                layout.splitter_sizes = splitter.sizes()

            # Detached tabs
            layout.detached_tabs = self.tabs.get_detached_geometries()

            # Sidebar collapsed groups
            layout.collapsed_groups = self.sidebar_nav.get_collapsed_groups()

            # Detached groups
            layout.detached_groups = self.tabs.get_detached_group_geometries()

            self._window_manager.save(layout)
        except Exception as e:
            logger.warning("Failed to save window layout: %s", e)

    def _restore_window_layout(self) -> None:
        """Restore window arrangement from previous session."""
        try:
            layout = self._window_manager.load()

            # Main window geometry
            if layout.main_geometry:
                from PySide6.QtCore import QRect
                g = layout.main_geometry
                self.setGeometry(QRect(
                    g.get("x", 100), g.get("y", 100),
                    g.get("w", 1400), g.get("h", 900),
                ))

            if layout.main_maximized:
                self.showMaximized()

            # Active tab (by name first, fall back to index)
            if layout.active_tab_name:
                self.tabs.select_tab_by_title(layout.active_tab_name)
                self.sidebar_nav.set_active_tab(layout.active_tab_name)
            elif 0 <= layout.active_tab < self.tabs.count():
                self.tabs.setCurrentIndex(layout.active_tab)

            # Splitter sizes
            if layout.splitter_sizes:
                splitter = self.centralWidget()
                if hasattr(splitter, "setSizes"):
                    splitter.setSizes(layout.splitter_sizes)

            # Sidebar collapsed groups
            if layout.collapsed_groups:
                self.sidebar_nav.set_collapsed_groups(layout.collapsed_groups)

            # Detached tabs (restore after a short delay so UI is ready)
            if layout.detached_tabs:
                QTimer.singleShot(
                    500,
                    lambda: self.tabs.restore_detached(layout.detached_tabs),
                )
        except Exception as e:
            logger.warning("Failed to restore window layout: %s", e)

    def _on_about(self) -> None:
        """Show about dialog."""
        QMessageBox.about(
            self,
            "Über PyMon",
            "<h2>PyMon v0.2.0</h2>"
            "<p>EVE Online Character Monitor</p>"
            "<p>Ein Python-Rewrite von EVEMon mit modernem ESI-API.</p>"
            "<p>Features: ID→Name Auflösung, Portraits, Skill-Completion-Benachrichtigungen, "
            "Killmail-Details, Wallet Transactions, Kontakte mit Namen, "
            "Kalender, Research, Medaillen, System Tray u.v.m.</p>"
            "<p>API: <a href='https://esi.evetech.net'>ESI (EVE Swagger Interface)</a></p>"
            "<p>Lizenz: GPL v2</p>",
        )

    def _on_setup_wizard(self) -> None:
        """Re-launch the first-run setup wizard from the Help menu."""
        from pymon.ui.setup_wizard import SetupWizard

        wizard = SetupWizard(self.config, parent=self)
        wizard.exec()

    # ══════════════════════════════════════════════════════════════════
    #  LIFECYCLE
    # ══════════════════════════════════════════════════════════════════

    def closeEvent(self, event) -> None:
        """Cleanup on window close."""
        # If tray is available and not explicitly quitting, minimize to tray
        if self._tray_icon and not self._really_quit:
            self.hide()
            event.ignore()
            return

        self.shutdown()
        super().closeEvent(event)

    def shutdown(self) -> None:
        """Stop all timers, threads, and release resources."""
        if self._shutting_down:
            return  # prevent double shutdown
        self._shutting_down = True
        logger.info("Shutting down PyMon...")

        # 0. Save window layout before tearing down
        self._save_window_layout()

        # 0b. Re-dock all detached windows
        try:
            self.tabs.dock_all_groups()
            self.tabs.dock_all()
        except Exception:
            pass

        # 1. Stop all timers
        for timer in [self._refresh_timer, self._countdown_timer, self._eve_time_timer]:
            try:
                timer.stop()
            except Exception:
                pass

        # 2. Hide tray icon
        if self._tray_icon:
            try:
                self._tray_icon.hide()
            except Exception:
                pass

        # 3. Wait for background threads (max 3s total)
        alive = [t for t in self._bg_threads if t.is_alive()]
        if alive:
            logger.info("Waiting for %d background thread(s)...", len(alive))
            deadline = 3.0 / max(len(alive), 1)
            for t in alive:
                t.join(timeout=deadline)
                if t.is_alive():
                    logger.warning("Thread %s did not finish in time", t.name)

        # 4. Close databases
        for closeable in [self.sde, self.db]:
            try:
                closeable.close()
            except Exception:
                pass

        # 5. Schedule force-kill as absolute fallback
        QTimer.singleShot(2000, self._force_quit)
        logger.info("Shutdown complete")

    @staticmethod
    def _force_quit() -> None:
        """Force-quit if the process is still alive after cleanup."""
        import os
        logger.warning("Force-quitting PyMon (process stuck)")
        os._exit(0)
