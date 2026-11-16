# Fehler pro Beitrag isolieren, `processed` heißt terminal

Jeder Beitrag hat einen eigenen Status (`draft`, `ready`, `failed`). Ein fehlgeschlagener Themenbeitrag blockiert weder die Summary noch andere Themen. Ein `Protocol.processed` wird true, sobald die Summary und alle geplanten Beiträge terminal sind — also `ready` oder `failed`. Fehlgeschlagene Beiträge bleiben sichtbar und können über einen eigenen Retry-Endpoint erneut angestoßen werden.

Damit endet ein Lauf auch bei einem dauerhaft fehlerhaften Thema, ohne das ganze Protokoll für immer als „unprocessed“ zu blockieren. Der Preis ist, dass `processed` nicht „alles erfolgreich“ bedeutet; der Status der einzelnen Beiträge ist die Wahrheit.
