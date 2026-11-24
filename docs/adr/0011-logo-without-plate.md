# Logo ohne Platte

Das transparente RGBA-Logo wird an allen vier Vorkommen direkt auf das Bild komponiert: Summary-Cover 240 px, Summary-Card 112 px, Topic-Cover 288 px und Topic-Footer 104 px breit. Es gibt keine weiße Platte, kein Padding, keinen Plattenradius, keine Maske, keinen Schatten und keinen Glow. Das Logo wird weiterhin über seinen Alpha-Kanal beschnitten, im Seitenverhältnis skaliert und ohne Flatten auf Weiß gezeichnet.

Die Anker bleiben stabil: Summary-Cover und Summary-Card oben links, Topic-Cover oben links, Topic-Footer rechtsbündig zur 600-px-Textspalte. Die Logo-Ink-Kante liegt am Anker; die frühere Padding-Verschiebung entfällt. Ein fehlendes oder vollständig transparentes Logo bleibt ein harter Render-Fehler. Der Logo-Cache bleibt pfadbasiert; nach einem Dateiaustausch ist ein App-Neustart erforderlich, eine mtime-Invalidierung wird bewusst nicht eingebaut.

Der Grund: Die weiße Platte ließ die Cover wie eine Collage wirken und dominierte das Bild. Das transparente Logo reicht für die Marke; den Kontrast liefert die ruhige, helle obere Bildzone der Prompts beziehungsweise eine später ausgetauschte Logo-Datei. Diese Entscheidung löst ADR 0007 ab.

## Nachtrag: Asset mit eigener weißer Platte

Das aktuelle Asset `gossip-logo-weiss-bgr.png` bringt eine eigene weiße, abgerundete Platte mit transparenten Ecken mit. Für dieses Asset ist die Regel „Logo ohne Platte“ damit abgelöst: Die Platte ist Teil der Marke und wird unverändert mitgerendert. Der Renderer fügt weiterhin keine zusätzliche Platte, kein Padding, keinen Plattenradius, keine Maske, keinen Schatten und keinen Glow hinzu. Die Alpha-Beschneidung, das Seitenverhältnis, die Anker, der harte Fehler bei fehlendem oder leerem Logo und der pfadbasierte Cache bleiben unverändert.
