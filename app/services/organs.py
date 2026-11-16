"""Deterministic Organ resolution from the finite seed list.

The mapping is deliberately exact and case-sensitive after stripping
surrounding whitespace. A missing title is an error: the pipeline must never
invent or fuzzy-match an official Organ name.
"""

ORGAN_BY_PROTOCOL_TITLE: dict[str, str] = {
    "Gemeinderat": "Gemeinderat Rosdorf",
    "Ortsrat Atzenhausen": "Ortsrat Atzenhausen",
    "Ortsrat Dahlenrode": "Ortsrat Dahlenrode",
    "Ortsrat Dramfeld": "Ortsrat Dramfeld",
    "Ortsrat Mengershausen": "Ortsrat Mengershausen",
    "Ortsrat Obernjesa": "Ortsrat Obernjesa",
    "Ortsrat Sieboldshausen": "Ortsrat Sieboldshausen",
    "Ortsrat Volkerode": "Ortsrat Volkerode",
    "Feuerwehrausschuss": "Feuerwehrausschuss",
    "Ausschuss Bau, Umwelt und Verkehr": "Ausschuss Bau, Umwelt und Verkehr",
    "Ausschuss Sport, Kultur und Soziales": "Ausschuss Sport, Kultur und Soziales",
    "Ausschuss Wirtschaft, Finanzen, Personal und Digitalisierung":
        "Ausschuss Wirtschaft, Finanzen, Personal und Digitalisierung",
}


class UnknownOrganError(Exception):
    """Raised when a protocol title is not in the finite Organ seed list."""

    def __init__(self, protocol_title: str):
        self.protocol_title = protocol_title
        super().__init__(
            f"Unknown organ for protocol title {protocol_title!r}; "
            "extend ORGAN_BY_PROTOCOL_TITLE instead of inventing a name"
        )


def resolve_organ(protocol_title: str) -> str:
    """Return the official Organ name for a protocol title.

    Only surrounding whitespace is normalised; matching is exact and
    case-sensitive because the seed list mirrors SessionNet titles.
    """
    key = protocol_title.strip()
    try:
        return ORGAN_BY_PROTOCOL_TITLE[key]
    except KeyError:
        raise UnknownOrganError(protocol_title) from None
