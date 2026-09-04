# Claude Cute

![The dragon reacting to a Claude Code session](docs/demo.gif)

**[English](#english) · [Español](#español)**

---

## English

A desktop widget for Windows: a pixel-art dragon that floats above your windows
and reacts in real time to what your Claude Code session is doing.

Send it a prompt and it starts thinking. Run a tool and it breathes fire.
Finish, and it settles down.

### What it does

It reacts to Claude Code, telling apart up to **16 states**:

| State | When it shows up |
|---|---|
| `idle` / `idle-sleep` | Nothing going on; falls asleep after 5 minutes |
| `thinking` | Claude is reasoning |
| `working` + `-bash` `-edit` `-read` `-web` `-agent` | Using a tool, depending which |
| `waiting` | **Claude is waiting for you** |
| `done` | Finished answering |
| `error` / `error-api` | A command or the API failed |
| `wake` / `sleep` | The session starts or ends |
| `compacting` | Claude is compacting the context |

Each one has its own pixel-art animation. A state without sprites of its own
inherits its ancestor's, so a new character is viable with only a few folders
drawn. See [docs/SPRITES.md](docs/SPRITES.md).

Also:

- Floats above every other window, frameless and with a transparent background.
- Stays out of the taskbar and Alt+Tab, and leaves nothing next to the clock:
  it shows up with your session and goes away with it.
- Drags with the left button, and **remembers where you left it**.
- Right click on the avatar to force a state, pick a character, hide it for a
  while or quit.

### Requirements

- Windows (Linux with X11 should work, but see the table below)
- Python 3.10 or newer
- Claude Code (so the avatar reacts on its own; without it the widget still
  runs and states can be pushed by hand)

#### Where it runs

| Platform | |
|---|---|
| Windows | ✅ used daily |
| Claude Code in a terminal or an IDE | ✅ everything works |
| The Claude desktop app | ✅ everything works — but it [hides hook errors](#if-the-dragon-does-not-show-up) |
| Windows without Git for Windows | ⚠️ the plugin's hooks need `bash` — [there is a way round it](#if-the-dragon-does-not-show-up) |
| Linux with X11 | ⚠️ **written for it, never run on it.** Nothing in the code touches Windows-only APIs and the launcher is there, but nobody has started this on a Linux desktop yet. Reports welcome |
| Linux with Wayland | ⬜ the dragon shows up and reacts, but **cannot be moved**: Wayland does not let a window place itself. Planned after the first release |
| macOS | ⬜ planned after the first release |

### Installing it

```
/plugin marketplace add EmmanuelUnsc/Claude-Cute
/plugin install claude-cute
```

Two commands, and that is the whole thing. No clone, no `pip`, and nothing to
answer: the plugin works out for itself which command starts Python here, by
trying them and keeping the first one that answers.

It works the same in a terminal, in the IDE extensions and in the Claude
desktop app. The hooks travel with the plugin and point at their own folder, so
moving or renaming things cannot break them.

Then **open a new conversation.** Hooks are read when a session starts, so the
one you installed from never got them — reopening that same conversation works
too. On that first session the graphics library comes down into the plugin's
own folder: about 100 MB, so give it a couple of minutes before the dragon
turns up. Your system Python is never touched.

> **On Windows this needs [Git for Windows](https://git-scm.com/downloads/win).**
> The hooks run through a small shell script and Git Bash is what runs it.
> Claude Code treats Git for Windows as optional, so without it they do
> nothing — see [If the dragon does not show up](#if-the-dragon-does-not-show-up).

#### If the dragon does not show up

Run **`/claude-cute:doctor`** in Claude Code. Everything in the plugin fails
quietly on purpose: eighteen hooks fire on every tool call, so anything that
wrote to your screen would be unbearable noise. The reasons go to files
instead, and the doctor is what reads them back — including the tail of pip's
error if the graphics library failed to download, which nothing else will ever
show you.

Three causes worth knowing about, because none of them announces itself:

- **The desktop app does not show hook errors.** The terminal prints them; the
  desktop app shows nothing at all. If something in the chain is failing,
  running one session in a terminal is the fastest way to read the real
  message.
- **No `bash`.** On Windows without Git for Windows the hooks run nothing. Fix
  it by installing Git for Windows, or from a clone run `py install.py`, which
  registers the same hooks with a direct path to your Python and no shell
  involved. `py uninstall.py` undoes it. It sits alongside the plugin rather
  than replacing it, so nothing ends up duplicated.
- **A project that turns hooks off.** `"disableAllHooks": true` in any
  `settings.json` — global, project or local — stops all of them. If the dragon
  reacts everywhere except in one project, look for that key first.

#### If port 8770 is already taken

The widget listens on `127.0.0.1:8770`. If another program holds it, the widget
**moves to the next free port on its own** and records it in `config.json`. The
hook reads that same file, so nothing else is needed.

It only stops if what holds the port is another Claude Cute — that is the
single-instance control, and moving would quietly start a duplicate.

To pin a specific port, add it by hand:

```json
{ "port": 8771 }
```

### Using it

Order does not matter: the widget and Claude Code are independent. Start either
first, and close and reopen either without breaking anything.

There can only be **one widget at a time**. Launch it again while one is open
and the second one says so and exits instead of stacking another dragon.

#### It comes and goes with your session

The dragon is part of the work environment, not a program you administer. When
the last Claude Code session is gone it waits five minutes —restarting the VS
Code extension closes and reopens a session within seconds— and then closes on
its own.

A widget you started by hand, that no session ever reached, stays until you
close it. That is what you want while drawing sprites.

#### Hiding it for a while

**Hide for** takes a deadline: 15 minutes, 1 hour or 4 hours. It comes back on
its own when the time is up, so there is no way to leave the widget running
invisible with nothing left to click.

There is a step for each intention: *Hide for* if you want it gone a while,
*Quit* if you want it gone now — it comes back with your next session.

#### Why a state sometimes gets "skipped"

During heavy work the events come every few hundred milliseconds, and a 600 ms
animation only managed to show two frames out of six: you could not tell what
it was.

So an animation with something to say reserves **two full cycles** before
another one may replace it. Once its turn is up it jumps straight to whatever
is true at that moment — there is no queue, so a very short state may never be
seen. That is deliberate: queueing would make the avatar fall behind without
bound during a burst, showing what happened half a minute ago.

Three exceptions, so aesthetics never beat information:

- **`waiting`, `error`, `done`, `wake` and `sleep` come in immediately.** They
  announce something that loses its value if it arrives late.
- **`idle` and `thinking` reserve nothing.** They are the filler between
  interesting things; protecting them would delay the reaction to a prompt and
  steal screen time from the tool animations.
- The real state is always available at `/state`, unsmoothed.

It is tuned with `MIN_CYCLES` in `src/smoothing.py`. At `0` it goes back to the
instant behaviour.

#### What it remembers between launches

A `config.json` next to the project stores the avatar's position, the chosen
character, and the port if it had to move. It can be
deleted with no consequences: everything goes back to its default.

If the saved position no longer lands inside any screen — after unplugging a
monitor, say — it is discarded and the avatar returns to the corner instead of
hiding out of sight.

> **Installed as a plugin, updating starts it fresh.** Each version gets its
> own folder, so the new one arrives without the previous `config.json` and the
> avatar returns to the corner with its default character. Only the
> preferences: nothing else is lost.

### From a clone

This is the route for reading the code, drawing a character or running
the widget without Claude Code. If you only want the dragon on your
desktop, you do not need any of it — see [Installing it](#installing-it).

Unlike the plugin, this route wants the graphics library installed yourself.
From a terminal, in the project folder:

```bash
py -3 -m pip install -r requirements.txt
```

On Linux:

```bash
python3 -m pip install -r requirements.txt
```


On Windows, double click **`run.bat`**. On Linux, run **`run.sh`**:

```bash
bash run.sh
```

> Invoked as `bash run.sh` and not `./run.sh` on purpose: the executable bit
> does not survive a download, so telling you to `chmod` first would only add a
> step that fails silently if you skip it.

Or start it by hand:

```bash
pyw -3 main.py      # Windows
python3 main.py     # Linux
```

The avatar appears in the bottom-right corner and starts listening for events
on `127.0.0.1:8770`.

> **Why `pyw -3` and not `python` on Windows**: if you have several Pythons
> installed — the Microsoft Store alias, for instance — a bare `python` may
> pick the wrong one and fail with `ModuleNotFoundError: No module named
> 'PySide6'`. The Windows `py`/`pyw` launcher always picks the right one, and
> `pyw` also skips the console window.

#### Testing without Claude Code

```bash
curl -X POST http://127.0.0.1:8770/event -H "Content-Type: application/json" -d "{\"state\":\"working\"}"
```

| Endpoint | Method | Body | Returns |
|---|---|---|---|
| `/event` | POST | `{"event": "PreToolUse", "tool": "Bash"}` or `{"state": "working"}` | `{"state": "..."}` |
| `/state` | GET | — | `{"state": "..."}` |

The `tool` field is optional and refines `PreToolUse`: `Bash` gives
`working-bash`, `Edit` gives `working-edit`, and so on.

The POST requires the `Content-Type: application/json` header. That is not red
tape: without it, any page you visit could POST to this port from your own
browser. The server only listens on `127.0.0.1` and caps the body at 8 KB.

#### If it will not start

`run.bat` reports a missing `main.py`, a missing `py` launcher, or a PySide6
that will not import, showing the real error and waiting for you to read it.
The PySide6 check is a warning and not a barrier: if it fails, it tries to
start anyway.

If absolutely nothing happens, the most likely reason is that it is already
running — look for the dragon on screen, or close it with right click → Quit.

> Installed as a plugin instead? The causes are different ones — see
> [If the dragon does not show up](#if-the-dragon-does-not-show-up).

To see any error in full, run it with a console:

```bash
py -3 main.py
```

**`ModuleNotFoundError: No module named 'PySide6'`** even though you are sure
you installed it: check *where* it landed.

```bash
py -3 -c "import PySide6; print(PySide6.__file__)"
```

If the path contains `AppData\Local\Packages\...`, it is inside the private
storage of a packaged (MSIX) application and the rest of the system cannot see
it. Reinstall from a normal terminal.


### Project structure

```
Claude Cute/
├── main.py                  entry point: builds and wires everything
├── run.bat                  launcher, Windows
├── run.sh                   launcher, Linux
├── install.py               registers the hooks by hand, for machines with no bash
├── uninstall.py             removes them again
├── requirements.txt
│
├── .claude-plugin/
│   ├── plugin.json          what the plugin is
│   └── marketplace.json     catalogue pointing at this same repository
│
├── commands/
│   └── doctor.md            /claude-cute:doctor — why the dragon is not there
│
├── src/
│   ├── server.py            local HTTP server that receives the events
│   ├── states.py            which states exist, what inherits from what
│   ├── state_manager.py     the live state machine; source of truth
│   ├── animation_engine.py  loads the PNGs and hands out the current frame
│   ├── character.py         reads and validates character.json
│   ├── avatar_window.py     the overlay window
│   ├── smoothing.py         how long each animation is held
│   ├── menu.py              the right-click menu
│   └── config.py            preferences that survive a restart
│
├── hooks/
│   ├── hooks.json           the 18 events, with no absolute paths
│   ├── cute-python.sh       finds a Python 3.10+ so nobody has to be asked
│   ├── runtime.py           fetches PySide6 once, into its own folder
│   ├── launch.py            run at session start; makes sure it is running
│   └── notify.py            run by Claude Code; tells the widget
│
├── assets/<character>/<state>/frame_01.png …
└── tests/
```

### Characters

Each character is a folder inside `assets/`, with one subfolder per state and
an optional `character.json` setting its name, scale and speeds. If there is
more than one, pick it from **right click → Character**.

Adding one requires no code changes: drawing `idle/` is enough, because
everything else inherits.

The full guide — canvas, anchoring, palette, the list of states and what each
one represents — is in **[docs/SPRITES.md](docs/SPRITES.md)**.

While drawing, "Reload assets" in the context menu re-reads the PNGs from disk
without restarting the widget.

### Tests

```bash
py -3 -m unittest discover -s tests
```

They run in a few seconds and cover the state machine (event mapping,
inheritance, transitions, ordering, sessions, concurrency), the animation
engine (ancestor resolution, one-shot playback, characters), the HTTP server
(protocol, port selection), the hook, the preferences and the window. They run
headless and do not depend on the assets.

### Documentation

- **[docs/SPRITES.md](docs/SPRITES.md)** — everything needed to draw a
  character: canvas, anchoring, palette, budgets and the state list.
- **[docs/STATES.md](docs/STATES.md)** — what triggers each of the 16 states
  and how to reproduce it on purpose.

### What it touches, and how to leave

**Everything it touches is listed here.** Nothing else on your system is
modified.

| | |
|---|---|
| Claude Code's hooks | so it finds out what is happening |
| Its own folder | the sprites, and a `config.json` with the avatar's position |
| One port on loopback | 8770 by default, only reachable from your own machine |
| `~/.claude/claude-cute/` | **only if it had to fetch PySide6.** See below |

No registry keys, no autostart entries, and no outbound connections other than
that one download: the only socket the widget opens is a `listen` on
`127.0.0.1`.

#### About that one folder

The plugin carries the program, but it cannot carry the graphics library —
that is a hundred megabytes of platform-specific binaries. So the first time
the dragon is asked for on a machine without it, it fetches it once into
`~/.claude/claude-cute/`, and never again.

**Why not inside the plugin:** every plugin version gets a fresh folder, so
keeping it there would re-download those hundred megabytes on every update.

**The first launch takes a minute or two** while that happens, and the dragon
shows up when it is done. If it cannot be fetched — no network, no pip — there
is simply no dragon, and it will not keep retrying on every session. The reason
is written to `~/.claude/claude-cute/.install-failed`.

If you already have PySide6, none of this happens: the check costs a fifth of a
second and the folder is never created.

#### Uninstalling

If you installed the plugin:

```bash
claude plugin uninstall claude-cute@claude-cute
claude plugin marketplace remove claude-cute
```

From the desktop app, the **+** button next to the prompt box → *Plugins* →
*Manage plugins* does the same thing.

If you ran `py install.py`, undo it from the project folder:

```bash
py uninstall.py
```

It removes only its own entries and leaves the rest of the file alone. If you
wrote the hooks in by hand instead, remove that block from
`~/.claude/settings.json` yourself, and delete the project folder.

**And if it ever fetched PySide6 for you**, that lives in one directory:

```bash
rm -rf ~/.claude/claude-cute
```

**The dragon closes itself.** If it is on screen when you uninstall, it stops
receiving events and goes away on its own about five minutes later, the same
way it does when you close your last session.

### License

MIT — see [LICENSE](LICENSE).

**The sprites too.** Dragoncita was drawn for this project by the author
credited in `assets/dragoncita/character.json`, and ships under the same
licence as the code. Anyone adding a character is expected to fill in that
`author` field with their own name.

---

## Español

> La interfaz del widget (el menú) está en inglés. Esta sección es la
> traducción de la de arriba.

Widget de escritorio para Windows: un dragón pixel art que se queda flotando
sobre tus ventanas y reacciona en tiempo real a lo que está haciendo tu sesión
de Claude Code.

Cuando le envías un prompt se pone a pensar. Cuando ejecuta una herramienta,
escupe fuego. Cuando termina, se relaja.

### Qué hace

Reacciona a lo que hace Claude Code, distinguiendo hasta **16 estados**:

| Estado | Cuándo aparece |
|---|---|
| `idle` / `idle-sleep` | No pasa nada; se duerme a los 5 minutos |
| `thinking` | Claude está razonando |
| `working` + `-bash` `-edit` `-read` `-web` `-agent` | Usando una herramienta, según cuál |
| `waiting` | **Claude está esperando tu aprobación** |
| `done` | Terminó de responder |
| `error` / `error-api` | Falló un comando o la API |
| `wake` / `sleep` | Arranca o termina la sesión |
| `compacting` | Claude está compactando el contexto |

Cada uno tiene su propia animación pixel art. Un estado sin sprites propios
heredaría los de su ancestro, así que un personaje nuevo es viable dibujando
sólo unos pocos. Ver [docs/SPRITES.md](docs/SPRITES.md).

Además:

- Flota siempre encima de las demás ventanas, sin bordes y con fondo
  transparente.
- No aparece en la barra de tareas ni en Alt+Tab, y no deja nada junto al
  reloj: aparece con tu sesión y se va con ella.
- Se arrastra con el botón izquierdo, y **recuerda dónde lo dejaste**.
- Con click derecho sobre el avatar se fuerza un estado, se elige personaje, se
  oculta un rato o se sale.

### Requisitos

- Windows (Linux con X11 debería andar, pero mirá la tabla de abajo)
- Python 3.10 o superior
- Claude Code (para que el avatar reaccione solo; sin él, el widget igual corre
  y se le pueden empujar estados a mano)

#### Dónde corre

| Plataforma | |
|---|---|
| Windows | ✅ de uso diario |
| Claude Code en terminal o en un IDE | ✅ funciona todo |
| La app de escritorio de Claude | ✅ funciona todo — pero [oculta los errores de hook](#si-el-dragón-no-aparece) |
| Windows sin Git for Windows | ⚠️ los hooks del plugin necesitan `bash` — [hay una salida](#si-el-dragón-no-aparece) |
| Linux con X11 | ⚠️ **escrito para funcionar ahí, nunca ejecutado ahí.** Nada del código usa APIs exclusivas de Windows y el lanzador está hecho, pero nadie arrancó esto todavía en un escritorio Linux. Se agradecen reportes |
| Linux con Wayland | ⬜ el dragón aparece y reacciona, pero **no se puede mover**: Wayland no deja que una ventana se posicione sola. Previsto para después del primer lanzamiento |
| macOS | ⬜ previsto para después del primer lanzamiento |

### Instalarlo

```
/plugin marketplace add EmmanuelUnsc/Claude-Cute
/plugin install claude-cute
```

Dos comandos y eso es todo. Sin clonar, sin `pip` y sin nada que contestar: el
plugin averigua solo con qué comando arranca Python acá, probándolos y
quedándose con el primero que responde.

Funciona igual en una terminal, en las extensiones de IDE y en la app de
escritorio de Claude. Los hooks viajan con el plugin y apuntan a su propia
carpeta, así que mover o renombrar cosas no puede romperlos.

Después **abre una conversación nueva.** Los hooks se leen al empezar una
sesión, así que aquella desde la que instalaste nunca los recibió — volver a
abrir esa misma también sirve. En esa primera sesión se baja la biblioteca
gráfica a la carpeta del plugin: unos 100 MB, así que dale un par de minutos
antes de que aparezca el dragón. Tu Python del sistema no se toca nunca.

> **En Windows esto necesita [Git for Windows](https://git-scm.com/downloads/win).**
> Los hooks pasan por un script de shell y quien lo ejecuta es Git Bash. Claude
> Code trata a Git for Windows como opcional, así que sin él no hacen nada —
> mira [Si el dragón no aparece](#si-el-dragón-no-aparece).

#### Si el dragón no aparece

Ejecuta **`/claude-cute:doctor`** en Claude Code. Todo en el plugin falla en
silencio a propósito: dieciocho hooks disparan en cada llamada a herramienta,
así que cualquier cosa que escribiera en tu pantalla sería ruido insoportable.
Las razones van a archivos, y el doctor es lo que las lee de vuelta — incluida
la cola del error de pip si falló la descarga de la biblioteca gráfica, que es
algo que nada más te va a mostrar.

Tres causas que conviene conocer, porque ninguna se anuncia sola:

- **La app de escritorio no muestra los errores de hook.** La terminal sí; el
  escritorio no dice absolutamente nada. Si algo de la cadena está fallando,
  abrir una sesión en una terminal es la forma más rápida de leer el mensaje
  real.
- **No hay `bash`.** En Windows sin Git for Windows los hooks no ejecutan nada.
  Se arregla instalando Git for Windows, o desde un clon con `py install.py`,
  que registra los mismos hooks con la ruta directa a tu Python y ningún shell
  de por medio. `py uninstall.py` lo deshace. Convive con el plugin en vez de
  reemplazarlo, así que no se duplica nada.
- **Un proyecto que apaga los hooks.** `"disableAllHooks": true` en cualquier
  `settings.json` —global, del proyecto o local— los detiene todos. Si el
  dragón reacciona en todos lados menos en un proyecto, busca esa clave primero.

#### Si el puerto 8770 ya está ocupado

El widget escucha en `127.0.0.1:8770`. Si otro programa lo tiene tomado, al
arrancar te lo va a decir —distingue entre "ya hay un Claude Cute" y "hay un
extraño"— y puedes elegir otro agregando una línea a `config.json`, junto a
`main.py`:

```json
{ "puerto": 8771 }
```

El hook lee ese mismo archivo, así que con cambiarlo una vez alcanza.

### Cómo se usa

No importa el orden: el widget y Claude Code son independientes. Puedes abrir
cualquiera primero, y cerrar y reabrir cualquiera de los dos sin romper nada.

Sólo puede haber **un widget a la vez**. Si se lanza de nuevo estando abierto,
el segundo avisa y se cierra en vez de apilar otro dragón.

#### Viene y se va con tu sesión

El dragón es parte del entorno de trabajo, no un programa que haya que
administrar. Cuando se fue la última sesión de Claude Code espera cinco minutos
—reiniciar la extensión de VS Code cierra y reabre una sesión en segundos— y se
cierra solo.

Un widget que abriste a mano, al que nunca se le acercó una sesión, se queda
hasta que lo cierres. Es lo que hace falta para dibujar sprites.

#### Ocultarlo un rato

**Hide for** pide un plazo: 15 minutos, 1 hora o 4 horas. Vuelve solo al
cumplirse, así que no hay forma de dejar el widget corriendo invisible sin nada
que clickear para recuperarlo.

Hay un escalón para cada intención: *Hide for* si lo quieres lejos un rato,
*Quit* si lo quieres lejos ahora — vuelve en tu próxima sesión.

#### Por qué a veces "se salta" un estado

Durante el trabajo intenso los eventos se suceden cada pocos cientos de
milisegundos, y una animación de 600 ms alcanzaba a mostrar dos frames de seis:
no se llegaba a ver qué era.

Por eso una animación con algo que contar se reserva **dos vueltas completas**
antes de que otra pueda reemplazarla. Cuando cumple su turno, salta directo a
lo que sea verdad en ese momento — no hay cola, así que un estado muy breve
puede no verse nunca. Es deliberado: encolar haría que el avatar se atrasara
sin techo en una ráfaga, mostrando lo que pasó hace medio minuto.

Tres excepciones, para que la estética no le gane a la información:

- **`waiting`, `error`, `done`, `wake` y `sleep` entran de inmediato.** Avisan
  algo que pierde valor si llega tarde.
- **`idle` y `thinking` no reservan nada.** Son el relleno entre cosas
  interesantes; protegerlos retrasaría la reacción al prompt y le robaría
  pantalla a las animaciones de herramienta.
- El estado real siempre está disponible en `/state`, sin suavizar.

Se ajusta con `MIN_CYCLES` en `src/smoothing.py`. En `0` vuelve al
comportamiento instantáneo.

#### Qué recuerda entre arranques

Un `config.json` junto al proyecto guarda la posición del avatar, el personaje
elegido y el puerto, si tuvo que mudarse. Se puede borrar sin consecuencias: vuelve a los
valores por defecto.

Si la posición guardada ya no cae dentro de ninguna pantalla —por ejemplo tras
desconectar un monitor— se descarta y el avatar vuelve a la esquina, en vez de
quedar escondido fuera de la vista.

> **Instalado como plugin, actualizar lo deja como nuevo.** Cada versión
> estrena carpeta, así que la nueva llega sin el `config.json` anterior y el
> avatar vuelve a la esquina con su personaje por defecto. Sólo las
> preferencias: no se pierde nada más.

### Desde un clon

Esta es la vía para leer el código, dibujar un personaje o usar el widget
sin Claude Code. Si sólo quieres el dragón en tu escritorio no necesitas
nada de esto — mira [Instalarlo](#instalarlo).

A diferencia del plugin, esta vía quiere que instales la biblioteca gráfica vos.
Desde una terminal, en la carpeta del proyecto:

```bash
py -3 -m pip install -r requirements.txt     # Windows
python3 -m pip install -r requirements.txt   # Linux
```

La única dependencia es PySide6.

Para comprobar que quedó bien instalado:

```bash
py -3 -c "import PySide6; print(PySide6.__file__)"
```


En Windows, doble click en **`run.bat`**. En Linux, se corre **`run.sh`**:

```bash
bash run.sh
```

> Se invoca con `bash run.sh` y no con `./run.sh` a propósito: el permiso de
> ejecución no sobrevive a una descarga, así que pedirte un `chmod` antes sólo
> agregaría un paso que falla en silencio si se lo omite.

O a mano:

```bash
pyw -3 main.py      # Windows
python3 main.py     # Linux
```

El avatar aparece en la esquina inferior derecha y queda escuchando eventos en
`127.0.0.1:8770`.

> **Por qué `pyw -3` y no `python`**: si tienes varios Python instalados — el
> alias de Microsoft Store, por ejemplo — `python` a secas puede agarrar el
> equivocado y fallar con `ModuleNotFoundError: No module named 'PySide6'`. El
> launcher `py`/`pyw` de Windows siempre elige el correcto. `pyw` además evita
> la ventana de consola.

#### Probar sin Claude Code

```bash
curl -X POST http://127.0.0.1:8770/event -H "Content-Type: application/json" -d "{\"state\":\"working\"}"
```

| Endpoint | Método | Body | Devuelve |
|---|---|---|---|
| `/event` | POST | `{"event": "PreToolUse", "tool": "Bash"}` o `{"state": "working"}` | `{"state": "..."}` |
| `/state` | GET | — | `{"state": "..."}` |

El campo `tool` es opcional y refina `PreToolUse`: `Bash` da `working-bash`,
`Edit` da `working-edit`, y así.

El POST exige la cabecera `Content-Type: application/json`. No es capricho:
sin eso, cualquier página que visites podría hacerle un POST a este puerto
desde tu propio navegador. El servidor sólo escucha en `127.0.0.1` y limita el
cuerpo a 8 KB.

#### Si no arranca

`run.bat` avisa si falta `main.py`, si falta el launcher `py` o si no puede
importar PySide6, mostrando el error real y esperando a que lo leas. La
verificación de PySide6 es una advertencia, no una barrera: si falla, intenta
arrancar igual.

Si no pasa absolutamente nada, lo más probable es que ya esté corriendo —
buscá el dragón en la pantalla, o cerralo con click derecho → Quit.

> ¿Lo instalaste como plugin? Ahí las causas son otras — mira
> [Si el dragón no aparece](#si-el-dragón-no-aparece).

Para ver cualquier error completo, ejecútalo con consola:

```bash
py -3 main.py
```

**`ModuleNotFoundError: No module named 'PySide6'`** aunque parezca
haberlo instalado: revisa *dónde* quedó instalado.

```bash
py -3 -c "import PySide6; print(PySide6.__file__)"
```

Si la ruta contiene `AppData\Local\Packages\...`, está dentro del
almacenamiento privado de una aplicación empaquetada (MSIX) y el resto del
sistema no lo ve. Reinstalalo desde una terminal normal. El caso concreto que
motivó esta nota: un `pip install` corrido por un agente dentro del contenedor
de la app de escritorio de Claude — funcionaba ahí y no en Windows.


### Estructura del proyecto

```
Claude Cute/
├── main.py                  punto de entrada: arma y conecta todo
├── run.bat                  lanzador, Windows
├── run.sh                   lanzador, Linux
├── install.py               registra los hooks a mano, para máquinas sin bash
├── uninstall.py             los vuelve a quitar
│
├── .claude-plugin/
│   ├── plugin.json          qué es el plugin
│   └── marketplace.json     catálogo que apunta a este mismo repositorio
│
├── commands/
│   └── doctor.md            /claude-cute:doctor — por qué no está el dragón
├── requirements.txt
│
├── src/
│   ├── server.py            servidor HTTP local que recibe los eventos
│   ├── states.py            qué estados hay, quién hereda de quién
│   ├── state_manager.py     máquina de estados; fuente de verdad
│   ├── animation_engine.py  carga los PNG y entrega el frame que toca
│   ├── character.py         lee y valida el character.json
│   ├── avatar_window.py     la ventana overlay
│   ├── smoothing.py         cuánto se deja ver cada animación
│   ├── menu.py              el menú del click derecho
│   └── config.py            preferencias que sobreviven al reinicio
│
├── hooks/
│   ├── hooks.json           los 18 eventos, sin rutas absolutas
│   ├── cute-python.sh       busca un Python 3.10+ para no preguntarle a nadie
│   ├── runtime.py           baja PySide6 una vez, a su propia carpeta
│   ├── launch.py            corre al abrir sesión; se asegura de que esté vivo
│   └── notify.py            lo ejecuta Claude Code; avisa al widget
│
├── assets/
│   └── dragoncita/          un personaje = una carpeta
│       ├── personaje.json   nombre, escala, velocidades
│       ├── idle/  thinking/  working/  done/   …y el resto de estados
│
├── tests/                   máquina de estados y motor de animación
│
└── docs/
    ├── SPRITES.md           cómo dibujar un personaje
    └── STATES.md            qué dispara cada estado
```

### Personajes

Cada personaje es una carpeta dentro de `assets/`, con una subcarpeta por
estado y un `character.json` opcional que fija su nombre, escala y
velocidades. Si hay más de uno, se elige desde **click derecho → Character**.

Agregar uno no requiere tocar código: alcanza con dibujar `idle/`, porque todo
lo demás hereda.

La guía completa —lienzo, anclaje, paleta, la lista de estados con lo que
representa cada uno— está en **[docs/SPRITES.md](docs/SPRITES.md)**.

Mientras dibujas, "Reload assets" del menú contextual relee los PNG del
disco sin reiniciar el widget.

### Tests

```bash
py -3 -m unittest discover -s tests
```

Tardan unos segundos. Cubren la máquina de estados (mapeo de
eventos, herencia, transiciones, orden, sesiones, concurrencia), el motor de
animación (resolución por ancestros, una sola pasada, personajes), las
preferencias que sobreviven al reinicio y la ventana (posición recordada,
visibilidad, menú, espera mínima). Corren sin pantalla y sin depender de los
assets.

### Documentación

- **[docs/SPRITES.md](docs/SPRITES.md)** — cómo dibujar un personaje: formato,
  anclaje, paleta y la lista de estados.
- **[docs/STATES.md](docs/STATES.md)** — qué dispara cada uno de los 16
  estados y cómo provocarlo a propósito para probarlo.

### Estado

Funciona de punta a punta: los dieciséis estados dibujados, el widget que
aparece y se va con tu sesión, las preferencias que sobreviven al reinicio, el
plugin instalable con un comando y la suite de tests en verde.

Lo que se sabe que falta:

- **En Windows sin Git for Windows los hooks del plugin no corren**: empiezan
  con `bash` y ahí no hay ninguno. Esa máquina necesita `py install.py`.
- **La app de escritorio no muestra los errores de hook.** Falla igual que la
  terminal, pero en silencio, así que cualquier problema ahí se ve como que no
  pasa nada. `/claude-cute:doctor` existe por eso.
- **Varias sesiones comparten un único avatar** y gana el último evento, con
  dos excepciones: un aviso pendiente de otra sesión no se pisa, y cerrar una
  ventana sólo duerme al avatar si era la última viva.
- **Linux está escrito pero nunca probado**, y en Wayland el avatar no se puede
  mover: el sistema no deja que una ventana se ubique sola.
- **macOS**, sin probar.

### Qué toca, y cómo irse

**Todo lo que toca está en esta lista.** Nada más de tu sistema se modifica.

| | |
|---|---|
| Los hooks de Claude Code | para enterarse de lo que pasa |
| Su propia carpeta | los sprites, y un `config.json` con la posición del avatar |
| Un puerto en loopback | el 8770 por defecto, alcanzable sólo desde tu máquina |
| `~/.claude/claude-cute/` | **sólo si tuvo que bajar PySide6.** Ver abajo |

Ni claves del registro, ni entradas de inicio automático, ni conexiones
salientes más allá de esa descarga: el único socket que abre el widget es un
`listen` en `127.0.0.1`.

#### Sobre esa carpeta

El plugin trae el programa, pero no puede traer la biblioteca gráfica: son cien
megas de binarios distintos para cada sistema. Así que la primera vez que se
pide el dragón en una máquina que no la tiene, la baja una vez a
`~/.claude/claude-cute/` y nunca más.

**Por qué no adentro del plugin:** cada versión estrena carpeta, así que
tenerla ahí significaría volver a bajar esos cien megas en cada actualización.

**El primer arranque tarda un minuto o dos** mientras eso pasa, y el dragón
aparece cuando termina. Si no se puede —sin internet, sin pip— simplemente no
hay dragón, y no reintenta en cada sesión: el motivo queda escrito en
`~/.claude/claude-cute/.install-failed`.

Si ya tienes PySide6, nada de esto ocurre: la comprobación cuesta dos décimas de
segundo y la carpeta no se crea nunca.

#### Desinstalar

Si instalaste el plugin:

```bash
claude plugin uninstall claude-cute@claude-cute
claude plugin marketplace remove claude-cute
```

Desde la app de escritorio es lo mismo con el botón **+** al lado del cuadro de
texto → *Plugins* → *Manage plugins*.

Si ejecutaste `py install.py`, deshazlo desde la
carpeta del proyecto:

```bash
py uninstall.py
```

Saca solamente sus propias entradas y deja el resto del archivo intacto. Si en
cambio escribiste los hooks a mano, sacá ese bloque de
`~/.claude/settings.json` a mano, y borra la carpeta del proyecto.

**Y si alguna vez te bajó PySide6**, eso vive en una sola carpeta:

```bash
rm -rf ~/.claude/claude-cute
```

**El dragón se cierra solo.** Si estaba en pantalla al desinstalar, deja de
recibir eventos y se va a los cinco minutos, igual que cuando cierras tu última
sesión.

### Licencia

MIT. Ver [LICENSE](LICENSE).

**Los sprites también.** La dragoncita se dibujó para este proyecto, con el
crédito en `assets/dragoncita/character.json`, y va bajo la misma licencia que
el código. Quien agregue un personaje completa ese campo `author` con su
nombre.
