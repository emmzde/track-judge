import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ChartNoAxesColumnIncreasing,
  ChevronRight,
  CircleAlert,
  ExternalLink,
  FileAudio,
  FolderOpen,
  LayoutGrid,
  Link2,
  ListMusic,
  LoaderCircle,
  Plus,
  SquareTerminal,
  X,
} from "lucide-react";
import { InterfaceIcon, WindowIcon } from "./icons";
import { Button, Modal, Switch } from "./ui";
import { languages, translator } from "./strings";
import { Player } from "./Player";
import { Empty, Results } from "./Results";
import "@fontsource-variable/manrope/wght.css";
import "./style.css";

const initial = { status: "idle", log: [], result: null, error: "" };
function filename(source) {
  return source.split(/[\\/]/).filter(Boolean).at(-1) || source;
}

function WindowControls({ maximized, action, t }) {
  const controls = [
    ["minimize", "minimizeWindow", "minimize"],
    [
      "toggle-maximize",
      maximized ? "restoreWindow" : "maximizeWindow",
      maximized ? "restore" : "maximize",
    ],
    ["close", "closeWindow", "close"],
  ];
  return (
    <div
      className="window-controls"
      role="group"
      aria-label={t("windowControls")}
    >
      {controls.map(([command, label, icon]) => (
        <button
          type="button"
          key={command}
          data-window-action={command}
          aria-label={t(label)}
          title={t(label)}
          onClick={() => action(command)}
        >
          <WindowIcon name={icon} />
        </button>
      ))}
    </div>
  );
}

function App() {
  const [api, setApi] = useState(null),
    [page, setPage] = useState("studio"),
    [lang, setLang] = useState("ru"),
    [version, setVersion] = useState("");
  const [sources, setSources] = useState([]),
    [folder, setFolder] = useState(""),
    [options, setOptions] = useState({
      spectrum: true,
      json: true,
      cookies: true,
    });
  const [state, setState] = useState(initial),
    [modal, setModal] = useState(""),
    [draft, setDraft] = useState(""),
    [message, setMessage] = useState("");
  const [selected, setSelected] = useState(0);
  const [customCaption, setCustomCaption] = useState(false);
  const [maximized, setMaximized] = useState(false);
  const main = useRef(null),
    submitLock = useRef(false);
  const t = translator(lang),
    busy = state.status === "running",
    tracks = state.result?.candidates || [];
  useEffect(() => {
    let active = true;
    async function init() {
      const bridge = window.pywebview?.api;
      if (!bridge) return;
      try {
        const data = await bridge.initialize();
        if (active) {
          setFolder(data.folder);
          setVersion(data.version);
          setSources(data.sources);
          setCustomCaption(data.custom_caption);
          setMaximized(data.maximized);
          setApi(bridge);
        }
      } catch (e) {
        if (active) setMessage(e.message);
      }
    }
    if (window.pywebview?.api) init();
    else window.addEventListener("pywebviewready", init, { once: true });
    function updateWindowState(event) {
      setMaximized(event.detail);
    }
    window.addEventListener("trackjudge:window-state", updateWindowState);
    return () => {
      active = false;
      window.removeEventListener("pywebviewready", init);
      window.removeEventListener("trackjudge:window-state", updateWindowState);
    };
  }, []);
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);
  useLayoutEffect(() => {
    main.current?.scrollTo(0, 0);
  }, [page]);
  useEffect(() => {
    if (!busy || !api) return;
    let active = true,
      timer;
    async function read() {
      try {
        const next = await api.status();
        if (!active) return;
        setState(next);
        if (next.status === "running") {
          timer = setTimeout(read, 450);
          return;
        }
        submitLock.current = false;
        if (next.status === "done") {
          setSelected(0);
          setPage("analysis");
        }
      } catch (e) {
        if (active) {
          setMessage(e.message);
          timer = setTimeout(read, 1000);
        }
      }
    }
    read();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [api, busy]);
  async function perform(action) {
    try {
      return await action();
    } catch (e) {
      setMessage(e.message || String(e));
      return null;
    }
  }
  async function start() {
    if (!api || submitLock.current || !sources.length || !folder.trim()) return;
    submitLock.current = true;
    try {
      setMessage("");
      await api.start(
        sources,
        folder,
        options.spectrum,
        options.json,
        options.cookies,
      );
      setState({ ...initial, status: "running" });
    } catch (e) {
      submitLock.current = false;
      setMessage(e.message);
    }
  }
  function append(values) {
    if (!values?.length) return false;
    const next = Array.from(new Set([...sources, ...values]));
    if (next.length > 5) {
      setMessage(t("limit"));
      return false;
    }
    setSources(next);
    setMessage("");
    return true;
  }
  async function addFiles() {
    append(await perform(() => api.choose("files")));
  }
  async function addLinks(text) {
    const values = await perform(() => api.links(text));
    if (values && !values.length) {
      setMessage(t("invalid"));
      return;
    }
    if (append(values)) {
      setModal("");
      setDraft("");
    }
  }
  function linkDialog() {
    setDraft("");
    setMessage("");
    setModal("links");
  }
  useEffect(() => {
    function paste(e) {
      if (
        !api ||
        busy ||
        modal ||
        page !== "studio" ||
        /INPUT|TEXTAREA/.test(e.target.tagName)
      )
        return;
      const text = e.clipboardData?.getData("text");
      if (text && /https?:\/\//i.test(text)) {
        e.preventDefault();
        addLinks(text);
      }
    }
    window.addEventListener("paste", paste);
    return () => window.removeEventListener("paste", paste);
  });
  const nav = [
    ["studio", LayoutGrid],
    ["analysis", ChartNoAxesColumnIncreasing],
    ["log", SquareTerminal],
  ];
  const cards = [
    ["headphones", "files", FileAudio, addFiles],
    ["cassette", "links", Link2, linkDialog],
    [
      "console",
      "out",
      FolderOpen,
      () => {
        setDraft(folder);
        setModal("folder");
      },
    ],
  ];
  const close = () => {
    setModal("");
    setMessage("");
  };
  const alert = message && (
    <div role="alert" className="alert">
      <CircleAlert />
      <span>{message}</span>
      <Button
        variant="icon"
        aria-label={t("close")}
        onClick={() => setMessage("")}
      >
        <X />
      </Button>
    </div>
  );
  return (
    <div
      className="shell"
      data-ready={api ? "true" : undefined}
      data-custom-caption={customCaption ? "" : undefined}
    >
      <aside className="sidebar">
        <div className="brand">
          <img className="brand-mark" src="/brand/trackjudge.png" alt="" />
          <span>TrackJudge</span>
        </div>
        <nav aria-label={t("space")}>
          {nav.map(([key, Icon]) => (
            <button
              key={key}
              className={"nav-item " + (page === key ? "active" : "")}
              aria-current={page === key ? "page" : undefined}
              onClick={() => setPage(key)}
              title={t(key)}
            >
              <Icon />
              <span>{t(key)}</span>
            </button>
          ))}
        </nav>
        <div className="side-bottom">
          <button
            className="nav-item"
            onClick={() => perform(() => api.project())}
            title={t("project")}
          >
            <ExternalLink />
            <span>{t("project")}</span>
          </button>
          {version && <div className="version">v{version}</div>}
        </div>
      </aside>
      <main>
        <header className="topline">
          <h1>
            {t(
              page === "studio"
                ? "title"
                : page === "analysis"
                  ? "view"
                  : "log",
            )}
          </h1>
          <label className="language">
            <InterfaceIcon name="language" />
            <select
              aria-label={t("language")}
              value={lang}
              onChange={(e) => setLang(e.target.value)}
            >
              {languages.map((v) => (
                <option key={v} value={v}>
                  {v.toUpperCase()}
                </option>
              ))}
            </select>
          </label>
        </header>
        <div className="workspace-scroll" ref={main}>
          <div className="content page-enter" key={page}>
            {!modal && alert}
            {busy && (
              <div className="statusline" role="status">
                <LoaderCircle className="spin" />
                {t("running")}
                <button onClick={() => setPage("log")}>{t("log")} →</button>
              </div>
            )}
            {state.status === "error" && (
              <div role="alert" className="alert">
                <CircleAlert />
                <div>
                  <strong>{t("err")}</strong>
                  <p>{state.error}</p>
                </div>
                <button onClick={() => setPage("log")}>{t("log")} →</button>
              </div>
            )}
            {page === "studio" && (
              <>
                <div className="cards">
                  {cards.map(([art, title, Icon, action]) => (
                    <button
                      key={art}
                      data-links={title === "links" ? "true" : undefined}
                      className={"art-card art-" + art}
                      onClick={action}
                      disabled={!api || busy}
                    >
                      <img src={"/art/" + art + ".webp"} alt="" />
                      <strong className="art-caption">{t(title)}</strong>
                      <span className="card-action" aria-hidden="true">
                        <Icon />
                      </span>
                    </button>
                  ))}
                </div>
                <div className="workspace">
                  <section>
                    <div className="section-title">
                      <h2>{t("queue")}</h2>
                      <span className="counter">{sources.length} / 5</span>
                    </div>
                    <div className="panel source-panel">
                      {sources.length === 0 ? (
                        <Empty icon={ListMusic} title={t("empty")} />
                      ) : (
                        <ul className="sources">
                          {sources.map((source, i) => {
                            const url = /^https?:/i.test(source),
                              Icon = url ? Link2 : FileAudio;
                            let name = filename(source);
                            if (url) {
                              try {
                                name = new URL(source).hostname.replace(
                                  /^www\./,
                                  "",
                                );
                              } catch {}
                            }
                            return (
                              <li data-source key={source}>
                                <div className="source-icon">
                                  <Icon />
                                </div>
                                <div className="source-name">
                                  <strong>{name}</strong>
                                  <small title={source}>{source}</small>
                                </div>
                                <Button
                                  variant="icon"
                                  disabled={busy}
                                  aria-label={t("remove") + " " + name}
                                  onClick={() =>
                                    setSources(
                                      sources.filter((_, idx) => idx !== i),
                                    )
                                  }
                                >
                                  <X />
                                </Button>
                              </li>
                            );
                          })}
                        </ul>
                      )}
                      <div className="run-row">
                        <Button
                          disabled={!api || busy || !sources.length}
                          onClick={start}
                        >
                          {busy ? (
                            <LoaderCircle className="spin" />
                          ) : (
                            <Activity />
                          )}
                          {t(busy ? "running" : "start")}
                        </Button>
                      </div>
                    </div>
                  </section>
                  <section>
                    <div className="section-title">
                      <h2>{t("options")}</h2>
                    </div>
                    <div className="panel options">
                      {[
                        ["spectrum", "spectrum"],
                        ["json", "report"],
                        ["cookies", "security"],
                      ].map(([key, icon]) => (
                        <Switch
                          key={key}
                          icon={icon}
                          label={t(key)}
                          hint={t(key + "Hint")}
                          checked={options[key]}
                          disabled={busy}
                          onCheckedChange={(value) =>
                            setOptions({ ...options, [key]: value })
                          }
                        />
                      ))}
                      <button
                        className="folder-path"
                        aria-label={t("out")}
                        title={folder}
                        disabled={busy}
                        onClick={() => {
                          setDraft(folder);
                          setModal("folder");
                        }}
                      >
                        <FolderOpen />
                        <span>{folder}</span>
                        <ChevronRight />
                      </button>
                    </div>
                  </section>
                </div>
                {state.result && (
                  <button
                    className="statusline"
                    onClick={() => setPage("analysis")}
                  >
                    <ChartNoAxesColumnIncreasing />
                    {t("winner")} · {state.result.winner.file_name}
                    <ChevronRight />
                  </button>
                )}
              </>
            )}
            {page === "analysis" && (
              <Results
                result={state.result}
                lang={lang}
                t={t}
                selected={selected}
                select={setSelected}
                back={() => setPage("studio")}
                open={(kind, rank = 0) =>
                  perform(() => api.open_output(kind, rank))
                }
                save={(rank) => perform(() => api.save_spectrum(rank))}
              />
            )}
            {page === "log" && (
              <section className="panel log">
                {state.log.length ? (
                  <pre>{state.log.join("\n")}</pre>
                ) : (
                  <Empty
                    icon={SquareTerminal}
                    title={t("idleLog")}
                    hint={t("idleLogText")}
                  />
                )}
              </section>
            )}
          </div>
        </div>
      </main>
      {customCaption && (
        <WindowControls
          maximized={maximized}
          action={(command) => perform(() => api.window_action(command))}
          t={t}
        />
      )}
      <Player
        tracks={tracks}
        index={selected}
        select={setSelected}
        t={t}
        notify={setMessage}
      />
      <Modal
        open={modal === "links"}
        title={t("links")}
        description={t("urlText")}
        close={t("close")}
        onClose={close}
      >
        <textarea
          data-initial-focus
          aria-label={t("links")}
          placeholder="https://…"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.ctrlKey && e.key === "Enter") addLinks(draft);
          }}
        />
        {alert}
        <div className="actions">
          <Button
            data-add-links
            disabled={!draft.trim()}
            onClick={() => addLinks(draft)}
          >
            <Plus />
            {t("add")}
          </Button>
        </div>
      </Modal>
      <Modal
        open={modal === "folder"}
        title={t("out")}
        close={t("close")}
        onClose={close}
      >
        <label className="field-label">
          {t("copyPath")}
          <input
            data-initial-focus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
        </label>
        {alert}
        <div className="actions">
          <Button
            variant="secondary"
            onClick={async () => {
              const values = await perform(() => api.choose("folder"));
              if (values?.length) setDraft(values[0]);
            }}
          >
            <FolderOpen />
            {t("choose")}
          </Button>
          <Button
            disabled={!draft.trim()}
            onClick={() => {
              setFolder(draft.trim());
              close();
            }}
          >
            OK
          </Button>
        </div>
      </Modal>
    </div>
  );
}
createRoot(document.getElementById("root")).render(<App />);
