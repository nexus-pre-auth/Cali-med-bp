"""
Condition Extractor — Step 1 of the compliance engine.

Parses raw document text to identify:
  - Facility / occupancy type  (e.g., Occupied Hospital, Surgery Center)
  - Mechanical / electrical / plumbing systems
  - Room types and their adjacency
  - Seismic design data (zone, SDS, SD1, Ip factor)
  - Construction type and sprinkler status
  - Project location (county, city) for local amendments
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from src.parser.pdf_parser import ParsedDocument


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class SeismicData:
    seismic_zone: Optional[str] = None      # e.g. "D", "E"
    sds: Optional[float] = None             # Design spectral response Ss
    sd1: Optional[float] = None             # Design spectral response S1
    importance_factor: Optional[float] = None  # Ip
    site_class: Optional[str] = None        # A–F


@dataclass
class ProjectConditions:
    """Structured conditions extracted from project documents."""
    # Occupancy
    occupancy_type: Optional[str] = None        # e.g. "Occupied Hospital"
    facility_type: Optional[str] = None         # e.g. "Acute Care", "Clinic"
    licensed_beds: Optional[int] = None

    # Construction
    construction_type: Optional[str] = None     # e.g. "Type I-A"
    sprinklered: Optional[bool] = None
    building_height_ft: Optional[float] = None
    stories_above_grade: Optional[int] = None

    # Systems identified
    hvac_systems: list[str] = field(default_factory=list)
    plumbing_systems: list[str] = field(default_factory=list)
    electrical_systems: list[str] = field(default_factory=list)
    medical_gas_systems: list[str] = field(default_factory=list)

    # Rooms
    room_types: list[str] = field(default_factory=list)

    # Seismic
    seismic: SeismicData = field(default_factory=SeismicData)

    # Location
    county: Optional[str] = None
    city: Optional[str] = None
    state: str = "California"

    # Wildfire / WUI zone flag
    wui_zone: Optional[bool] = None   # True = project is in a Wildland-Urban Interface zone

    # Raw extraction confidence
    raw_snippets: dict[str, list[str]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Extraction patterns
# ---------------------------------------------------------------------------

OCCUPANCY_PATTERNS = [
    (r"\boccupied\s+hospital\b", "Occupied Hospital"),
    (r"\bacute[\s-]care\b", "Acute Care Hospital"),
    (r"\bsurgical?\s+center\b", "Surgical Center"),
    (r"\bambulatory\s+surgery\b", "Ambulatory Surgery Center"),
    (r"\bclinic\b", "Clinic"),
    (r"\bskilled\s+nursing\b", "Skilled Nursing Facility"),
    (r"\blong[\s-]term\s+care\b", "Long-Term Care Facility"),
    (r"\boutpatient\b", "Outpatient Facility"),
    (r"\bemergency\s+department\b", "Emergency Department"),
    (r"\bpsychiatric\b", "Psychiatric Facility"),
    (r"\brehabilitation\b", "Rehabilitation Facility"),
]

CONSTRUCTION_TYPE_PATTERN = re.compile(
    r"construction\s+type[:\s]+([IVX]+[\s\-][A-B])", re.I
)
SPRINKLER_PATTERN = re.compile(
    r"(fully?\s+sprinklered|NFPA\s+13\b|automatic\s+sprinkler)", re.I
)
HEIGHT_PATTERN = re.compile(r"building\s+height[:\s]+([\d.]+)\s*(?:ft|feet)", re.I)
STORIES_PATTERN = re.compile(r"(\d+)[\s-]+stor(?:y|ies)\s+(?:above\s+grade)?", re.I)
BEDS_PATTERN = re.compile(r"(?:(\d+)[\s-]+(?:licensed\s+)?beds?|(?:licensed\s+)?beds?[:\s]+(\d+))", re.I)

SEISMIC_ZONE_PATTERN = re.compile(r"seismic\s+(?:design\s+)?(?:category|zone)[:\s]+([A-F])", re.I)
SDS_PATTERN = re.compile(r"S[Dd][Ss][:\s]*([\d.]+)", re.I)
SD1_PATTERN = re.compile(r"S[Dd]1[:\s]*([\d.]+)", re.I)
IP_PATTERN = re.compile(r"I[Pp][:\s]*([\d.]+)", re.I)
SITE_CLASS_PATTERN = re.compile(r"site\s+class[:\s]+([A-F])", re.I)

HVAC_KEYWORDS = [
    "AHU", "air handling unit", "VAV", "heat pump", "chiller", "boiler",
    "exhaust fan", "supply fan", "DOAS", "dedicated outdoor air",
    "negative pressure", "positive pressure", "isolation room",
    "infection control", "HEPA filter", "MERV",
]

PLUMBING_KEYWORDS = [
    "medical gas", "oxygen", "vacuum", "compressed air", "nitrous oxide",
    "WAGD", "waste anesthesia", "sanitary", "storm drain", "hot water",
    "water heater", "backflow preventer", "eye wash", "emergency shower",
]

ELECTRICAL_KEYWORDS = [
    "generator", "essential electrical system", "EES", "critical branch",
    "life safety branch", "equipment branch", "UPS", "transfer switch",
    "ATS", "panelboard", "emergency power", "NFPA 99",
    "telehealth circuit", "dedicated circuit", "audio/video",
    "EV charging", "EVSE", "electric vehicle charging", "electric vehicle",
]

MEDICAL_GAS_KEYWORDS = [
    "oxygen manifold", "liquid oxygen", "LOX", "medical air compressor",
    "WAGD system", "vacuum pump", "gas outlet", "zone valve", "valve box",
    "zone valve box", "ZVB",
]

ROOM_TYPES = [
    "operating room", "OR", "procedure room", "ICU", "intensive care",
    "patient room", "patient care", "pharmacy", "laboratory", "lab",
    "radiology", "imaging", "MRI", "CT scan", "emergency room", "ER",
    "trauma room", "clean room", "sterile processing", "SPD", "CSSD",
    "soiled utility", "clean utility", "medication room", "nurse station",
    "isolation room", "negative pressure room", "NICU", "PACU",
    "recovery room", "waiting room", "toilet room", "shower room",
    "janitor closet", "electrical room", "mechanical room",
    "loading dock", "kitchen", "dietary", "laundry",
    "telehealth room", "telemedicine room", "telehealth",
    "behavioral health", "psychiatric", "mental health", "seclusion room",
    "parking garage", "parking structure",
]

WUI_PATTERN = re.compile(
    r"(wildland[\s-]urban\s+interface|"
    r"\bWUI\b|"
    r"fire\s+hazard\s+severity\s+zone|"
    r"\bFHSZ\b|"
    r"very\s+high\s+fire\s+hazard|"
    r"high\s+fire\s+(?:hazard|risk)\s+(?:area|zone)|"
    r"state\s+responsibility\s+area|"
    r"defensible\s+space)",
    re.I,
)

COUNTY_PATTERN = re.compile(
    r"(?:county\s+of\s+|)([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+county", re.I
)
CITY_PATTERN = re.compile(r"(?:city\s+of\s+)([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", re.I)


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------

class ConditionExtractor:
    """Extract structured project conditions from parsed documents."""

    def extract(self, doc: ParsedDocument) -> ProjectConditions:
        text = doc.full_text
        conditions = ProjectConditions()

        self._extract_occupancy(text, conditions)
        self._extract_construction(text, conditions)
        self._extract_seismic(text, conditions)
        self._extract_systems(text, conditions)
        self._extract_rooms(text, conditions)
        self._extract_location(text, conditions)
        self._extract_wui(text, conditions)

        return conditions

    # ------------------------------------------------------------------
    def _extract_occupancy(self, text: str, c: ProjectConditions) -> None:
        for pattern, label in OCCUPANCY_PATTERNS:
            if re.search(pattern, text, re.I):
                c.occupancy_type = label
                break

        m = BEDS_PATTERN.search(text)
        if m:
            c.licensed_beds = int(m.group(1) or m.group(2))

    def _extract_construction(self, text: str, c: ProjectConditions) -> None:
        m = CONSTRUCTION_TYPE_PATTERN.search(text)
        if m:
            c.construction_type = m.group(1).strip()

        if SPRINKLER_PATTERN.search(text):
            c.sprinklered = True

        m = HEIGHT_PATTERN.search(text)
        if m:
            c.building_height_ft = float(m.group(1))

        m = STORIES_PATTERN.search(text)
        if m:
            c.stories_above_grade = int(m.group(1))

    def _extract_seismic(self, text: str, c: ProjectConditions) -> None:
        s = c.seismic
        m = SEISMIC_ZONE_PATTERN.search(text)
        if m:
            s.seismic_zone = m.group(1).upper()

        m = SDS_PATTERN.search(text)
        if m:
            s.sds = float(m.group(1))

        m = SD1_PATTERN.search(text)
        if m:
            s.sd1 = float(m.group(1))

        m = IP_PATTERN.search(text)
        if m:
            s.importance_factor = float(m.group(1))

        m = SITE_CLASS_PATTERN.search(text)
        if m:
            s.site_class = m.group(1).upper()

    def _extract_systems(self, text: str, c: ProjectConditions) -> None:
        text_lower = text.lower()
        c.hvac_systems = [k for k in HVAC_KEYWORDS if k.lower() in text_lower]
        c.plumbing_systems = [k for k in PLUMBING_KEYWORDS if k.lower() in text_lower]
        c.electrical_systems = [k for k in ELECTRICAL_KEYWORDS if k.lower() in text_lower]
        c.medical_gas_systems = [k for k in MEDICAL_GAS_KEYWORDS if k.lower() in text_lower]

    def _extract_rooms(self, text: str, c: ProjectConditions) -> None:
        text_lower = text.lower()
        c.room_types = list({r for r in ROOM_TYPES if r.lower() in text_lower})

    def _extract_location(self, text: str, c: ProjectConditions) -> None:
        m = COUNTY_PATTERN.search(text)
        if m:
            c.county = m.group(1).strip()

        m = CITY_PATTERN.search(text)
        if m:
            c.city = m.group(1).strip()

    def _extract_wui(self, text: str, c: ProjectConditions) -> None:
        if WUI_PATTERN.search(text):
            c.wui_zone = True
