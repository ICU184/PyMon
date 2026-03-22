"""EVE notification type parser.

Translates ESI notification types to human-readable German descriptions
and categories.
"""

from __future__ import annotations

# Category → list of (type_prefix_or_exact, icon, description)
_NOTIFICATION_CATEGORIES: dict[str, tuple[str, str]] = {
    # War
    "AllWarDeclaredMsg": ("⚔️", "Kriegserklärung"),
    "AllWarRetractedMsg": ("🕊️", "Krieg zurückgezogen"),
    "AllWarFinishedMsg": ("🕊️", "Krieg beendet"),
    "AllWarInvalidatedMsg": ("🕊️", "Krieg ungültig"),
    "AllWarSurrenderMsg": ("🏳️", "Kapitulation"),
    "CorpWarDeclaredMsg": ("⚔️", "Corp-Kriegserklärung"),
    "CorpWarFightingLegalMsg": ("⚔️", "Kriegsrecht – Kampf legal"),
    "CorpWarRetractedMsg": ("🕊️", "Corp-Krieg zurückgezogen"),
    "CorpWarSurrenderMsg": ("🏳️", "Corp-Kapitulation"),
    "WarAdopted": ("⚔️", "Krieg übernommen"),
    "WarDeclared": ("⚔️", "War Declared"),
    "WarInherited": ("⚔️", "Krieg geerbt"),
    "WarRetractedByConcord": ("🕊️", "Krieg von CONCORD zurückgezogen"),

    # Structure
    "StructureAnchoring": ("🏗️", "Struktur verankert"),
    "StructureDestroyed": ("💥", "Struktur zerstört"),
    "StructureFuelAlert": ("⛽", "Treibstoff-Alarm"),
    "StructureLostArmor": ("🛡️", "Panzerung verloren"),
    "StructureLostShields": ("🛡️", "Schilde verloren"),
    "StructureOnline": ("✅", "Struktur online"),
    "StructureServicesOffline": ("⚠️", "Dienste offline"),
    "StructureUnanchoring": ("🔧", "Struktur wird abgebaut"),
    "StructureUnderAttack": ("🚨", "Struktur wird angegriffen!"),
    "StructureWentHighPower": ("⚡", "Hochenergie-Modus"),
    "StructureWentLowPower": ("🔋", "Niedrigenergie-Modus"),
    "StructuresReinforcementChanged": ("🔄", "Verstärkungs-Timer geändert"),
    "MoonminingAutomaticFracture": ("🌙", "Mond-Chunk bereit"),
    "MoonminingExtractionStarted": ("🌙", "Mond-Extraktion gestartet"),
    "MoonminingExtractionFinished": ("🌙", "Mond-Extraktion fertig"),
    "MoonminingExtractionCancelled": ("🌙", "Mond-Extraktion abgebrochen"),
    "MoonminingLaserFired": ("🌙", "Mond-Laser gefeuert"),
    "TowerAlertMsg": ("🏗️", "POS-Alarm"),
    "TowerResourceAlertMsg": ("⛽", "POS-Ressourcen-Alarm"),

    # Sovereignty
    "SovAllClaimAquiredMsg": ("🏴", "Sovereignty beansprucht"),
    "SovAllClaimLostMsg": ("🏴", "Sovereignty verloren"),
    "SovCommandNodeEventStarted": ("🏴", "Command Node Event"),
    "SovStructureDestroyed": ("💥", "Sov-Struktur zerstört"),
    "SovStructureReinforced": ("🔄", "Sov-Struktur reinforced"),
    "SovStructureSelfDestructRequested": ("💣", "Selbstzerstörung angefragt"),
    "SovStructureSelfDestructFinished": ("💣", "Selbstzerstörung beendet"),
    "SovStructureSelfDestructCancel": ("✋", "Selbstzerstörung abgebrochen"),

    # Corporation
    "CorpAppNewMsg": ("📋", "Neue Corp-Bewerbung"),
    "CorpAppAcceptMsg": ("✅", "Corp-Bewerbung angenommen"),
    "CorpAppRejectMsg": ("❌", "Corp-Bewerbung abgelehnt"),
    "CorpAppInvitedMsg": ("📩", "Corp-Einladung erhalten"),
    "CharAppAcceptMsg": ("✅", "Bewerbung angenommen"),
    "CharAppRejectMsg": ("❌", "Bewerbung abgelehnt"),
    "CharAppWithdrawMsg": ("↩️", "Bewerbung zurückgezogen"),
    "CharLeftCorpMsg": ("👋", "Character left corporation"),
    "CorpKicked": ("🚪", "Aus Corp geworfen"),
    "CorpNewCEOMsg": ("👑", "Neuer CEO"),
    "CorpDividendMsg": ("💰", "Corp-Dividende"),
    "CorpTaxChangeMsg": ("📊", "Corp Taxn geändert"),
    "CorpVoteCEORevokedMsg": ("🗳️", "CEO-Abstimmung aufgehoben"),
    "CorpNewsMsg": ("📰", "Corp-Nachricht"),

    # Alliance
    "AllianceCapitalChanged": ("🏛️", "Allianz-Hauptstadt geändert"),
    "AllyJoinedWarAggressorMsg": ("⚔️", "Alliierter tritt Krieg bei"),
    "AllyJoinedWarDefenderMsg": ("🛡️", "Verteidiger erhält Alliierte"),

    # Bounties / Kills
    "BountyClaimMsg": ("💰", "Kopfgeld eingelöst"),
    "KillReportFinalBlow": ("⚔️", "Final Blow – Kill Report"),
    "KillReportVictim": ("💀", "Kill Report – du wurdest zerstört"),
    "KillRightAvailable": ("⚔️", "Kill Right verfügbar"),
    "KillRightAvailableOpen": ("⚔️", "Kill Right offen verfügbar"),
    "KillRightUsed": ("⚔️", "Kill Right eingesetzt"),

    # Industry
    "IndustryTeamAuctionWon": ("🏭", "Team-Auktion gewonnen"),
    "IndustryTeamAuctionLost": ("🏭", "Team-Auktion verloren"),

    # Contacts
    "ContactAdd": ("📇", "Kontakt hinzugefügt"),
    "ContactEdit": ("📇", "Kontakt bearbeitet"),

    # Insurance
    "InsurancePayoutMsg": ("💵", "Versicherung ausgezahlt"),
    "InsuranceFirstShipMsg": ("🚀", "Erste Versicherung"),
    "InsuranceExpirationMsg": ("⏰", "Versicherung abgelaufen"),
    "InsuranceIssuedMsg": ("📋", "Versicherung abgeschlossen"),
    "InsuranceInvalidatedMsg": ("❌", "Versicherung ungültig"),

    # Incursion
    "IncursionCompletedMsg": ("👾", "Incursion abgeschlossen"),

    # Loyalty Store / Offers
    "LocateCharMsg": ("🔍", "Character located"),

    # Misc
    "CloneActivationMsg": ("🧬", "Klon aktiviert"),
    "CloneActivationMsg2": ("🧬", "Klon aktiviert"),
    "CloneMovedMsg": ("🧬", "Klon verschoben"),
    "CloneRevokedMsg1": ("🧬", "Klon widerrufen"),
    "CloneRevokedMsg2": ("🧬", "Klon widerrufen"),
    "JumpCloneDeleteMsg": ("🧬", "Jump Clone gelöscht"),
    "SkillTrainingComplete": ("📚", "Skill-Training abgeschlossen"),
    "ExpertSystemExpired": ("📚", "Expert System abgelaufen"),

    # Billing
    "BillOutOfMoneyMsg": ("💸", "Insufficient funds for bill"),
    "BillPaidCorpAllMsg": ("💰", "Corp-Rechnung bezahlt"),
    "CharMedal": ("🏅", "Medaille erhalten"),
}


def parse_notification_type(notification_type: str) -> tuple[str, str]:
    """Return (icon, description) for a notification type.

    Falls back to the raw type name if unknown.
    """
    if notification_type in _NOTIFICATION_CATEGORIES:
        return _NOTIFICATION_CATEGORIES[notification_type]

    # Fallback: try partial matches
    for key, (icon, desc) in _NOTIFICATION_CATEGORIES.items():
        if key.lower() in notification_type.lower():
            return icon, desc

    return "📌", notification_type


def get_notification_category(notification_type: str) -> str:
    """Get a broad category for grouping notifications."""
    t = notification_type.lower()
    if "war" in t:
        return "Krieg"
    elif "struct" in t or "tower" in t or "moon" in t:
        return "Strukturen"
    elif "sov" in t:
        return "Sovereignty"
    elif "corp" in t or ("char" in t and "app" in t):
        return "Corporation"
    elif "kill" in t or "bounty" in t:
        return "Kampf"
    elif "insurance" in t:
        return "Versicherung"
    elif "clone" in t or "skill" in t:
        return "Character"
    elif "contact" in t:
        return "Contacts"
    elif "bill" in t or "dividend" in t:
        return "Finanzen"
    return "Sonstiges"
