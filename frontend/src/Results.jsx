import React, { useState } from "react";
import {
  AudioLines,
  ChartNoAxesColumnIncreasing,
  ExternalLink,
  FolderOpen,
  Download,
  Check,
  Maximize2,
} from "lucide-react";
import { Button, Modal } from "./ui";
import { InterfaceIcon } from "./icons";
import { clock } from "./Player";

export function Empty({ icon: Icon, title, hint, children }) {
  return (
    <div className="empty">
      <div className="empty-icon">
        <Icon />
      </div>
      <strong>{title}</strong>
      {hint && <p>{hint}</p>}
      {children}
    </div>
  );
}
export function Results({
  result,
  t,
  lang,
  select,
  selected,
  open,
  save,
  back,
}) {
  const [zoom, setZoom] = useState(null),
    [saved, setSaved] = useState({});
  if (!result)
    return (
      <section className="panel">
        <Empty
          icon={ChartNoAxesColumnIncreasing}
          title={t("none")}
          hint={t("noneText")}
        >
          <Button variant="secondary" onClick={back}>
            {t("back")}
          </Button>
        </Empty>
      </section>
    );
  return (
    <div className="result-list">
      <section className="winner panel">
        <div>
          <small>{t("winner")}</small>
          <h2>{result.winner.file_name}</h2>
          <p className="path">{result.winner.saved_file}</p>
        </div>
        <div className="actions">
          <Button onClick={() => open("winner")}>
            <ExternalLink />
            {t("openFile")}
          </Button>
          <Button variant="secondary" onClick={() => open("folder")}>
            <FolderOpen />
            {t("openFolder")}
          </Button>
          {result.report && (
            <Button variant="secondary" onClick={() => open("report")}>
              <InterfaceIcon name="report" />
              {t("report")}
            </Button>
          )}
        </div>
      </section>
      <section className="panel ranking">
        <h2>{t("ranking")}</h2>
        {result.candidates.map((item) => (
          <a key={item.rank} href={"#candidate-" + item.rank}>
            <span className="rank">#{item.rank}</span>
            <strong>{item.file_name}</strong>
            <meter
              min="0"
              max="100"
              value={item.score}
              aria-label={t("score")}
            />
            <span>{item.score.toFixed(1)}</span>
          </a>
        ))}
      </section>
      {result.candidates.map((item, i) => (
        <article
          id={"candidate-" + item.rank}
          className="panel candidate"
          key={item.rank}
        >
          <div className="row between">
            <div className="row min-w-0">
              <span className="rank">#{item.rank}</span>
              <h3>{item.file_name}</h3>
            </div>
            <Button
              variant={selected === i ? "default" : "secondary"}
              onClick={() => select(i)}
              aria-label={t("listen") + " " + item.file_name}
            >
              <AudioLines />
              {t("listen")}
            </Button>
          </div>
          <div className="metrics">
            {[
              [t("score"), item.score.toFixed(1) + " / 100"],
              [
                t("cutoff"),
                (item.effective_cutoff_hz / 1000).toFixed(1) + " kHz",
              ],
              [t("full"), (item.raw_cutoff_hz / 1000).toFixed(1) + " kHz"],
              [t("auth"), Math.round(item.authenticity) + " / 100"],
              [t("duration"), clock(item.source_duration_seconds)],
              [
                t("format"),
                item.codec.toUpperCase() + " · " + item.bitrate_kbps + " kb/s",
              ],
            ].map(([label, value]) => (
              <div key={label}>
                <small>{label}</small>
                <strong>{value}</strong>
              </div>
            ))}
          </div>
          <p className="measured-format">
            {item.sample_rate_hz.toLocaleString(lang)} Hz · {item.channels}{" "}
            {t("channels")} · {item.source}
          </p>
          <p>{item.explanation[lang]}</p>
          {item.source_duration_seconds - item.analysis_duration_seconds >
            1 && (
            <p>
              {t("clip")}{" "}
              {clock(
                (item.source_duration_seconds -
                  item.analysis_duration_seconds) /
                  2,
              )}{" "}
              · {clock(item.analysis_duration_seconds)}
            </p>
          )}
          {item.image && (
            <>
              <button
                className="spectrum-image"
                onClick={() => setZoom({ item, open: true })}
                aria-label={t("zoom")}
              >
                <img
                  src={item.image}
                  alt={t("spectrum") + " — " + item.file_name}
                />
                <Maximize2 />
              </button>
              <Button
                variant="secondary"
                disabled={!!saved[i]}
                onClick={async () => {
                  if (await save(item.rank))
                    setSaved((v) => ({ ...v, [i]: true }));
                }}
              >
                {saved[i] ? <Check /> : <Download />}
                {t(saved[i] ? "saved" : "save")}
              </Button>
              <Button
                variant="secondary"
                onClick={() => open("spectrum", item.rank)}
              >
                <ExternalLink />
                {t("openPng")}
              </Button>
            </>
          )}
        </article>
      ))}
      {!!result.failures.length && (
        <div className="panel failures">
          <h3>{t("issues")}</h3>
          {result.failures.map((item, i) => (
            <p key={i}>
              {item.url}
              <br />
              {item.reason}
            </p>
          ))}
        </div>
      )}
      {zoom && (
        <Modal
          open={zoom.open}
          wide
          title={zoom.item.file_name}
          close={t("close")}
          onClose={() => setZoom({ ...zoom, open: false })}
        >
          <img
            className="full-spectrum"
            src={zoom.item.image}
            alt={t("spectrum")}
          />
        </Modal>
      )}
    </div>
  );
}
