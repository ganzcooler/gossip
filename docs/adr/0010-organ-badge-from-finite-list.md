# Organ-Badge aus einer endlichen Liste

Der Organname im Badge wird deterministisch aus `Protocol.title` und einer endlichen Liste offizieller Organnamen abgeleitet. v1 nutzt dafür kein LLM. Die Liste startet als Seed aus den vorhandenen `Protocol.title`-Werten; `Gemeinderat` wird zu `Gemeinderat Rosdorf` kanonisiert. Die Liste kann nachgeliefert und erweitert werden; fehlt ein Titel, wird kein Name geraten, sondern der Beitrag nicht gerendert.

Der Grund: Der Badge ist eine Herkunftsangabe. Ein erfundener oder abgekürzter Organname wäre ein Faktenfehler; eine deterministische Zuordnung ist prüfbar und reproduzierbar.
