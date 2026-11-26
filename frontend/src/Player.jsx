import React, { useEffect, useRef, useState } from "react";
import WaveSurfer from "wavesurfer.js";
import { Play, Pause, SkipBack, SkipForward, Volume2 } from "lucide-react";
import { Button } from "./ui";

export function clock(seconds = 0) {
  const total = Math.floor(Math.max(0, seconds));
  return Math.floor(total / 60) + ":" + String(total % 60).padStart(2, "0");
}

export function Player({ tracks, index, select, t, notify }) {
  const container = useRef(null),
    player = useRef(null);
  const [position, setPosition] = useState(0),
    [playing, setPlaying] = useState(false),
    [ready, setReady] = useState(false);
  const [volume, setVolume] = useState(0.75);
  const latest = useRef({ t, notify, volume });
  latest.current = { t, notify, volume };
  const track = tracks[index],
    sample = track?.preview;
  useEffect(() => {
    setReady(false);
    setPlaying(false);
    setPosition(0);
    if (!sample || !container.current) return;
    const style = getComputedStyle(document.documentElement);
    const token = (name) => style.getPropertyValue(name).trim();
    const wave = WaveSurfer.create({
      container: container.current,
      waveColor: token("--muted"),
      progressColor: token("--accent"),
      cursorColor: token("--accent"),
      barWidth: parseInt(token("--wave-bar")),
      barGap: parseInt(token("--wave-gap")),
      barRadius: 2,
      height: parseInt(token("--wave-height")),
      normalize: true,
    });
    player.current = wave;
    let active = true;
    wave.setVolume(latest.current.volume);
    wave.on("ready", () => setReady(true));
    wave.on("timeupdate", setPosition);
    wave.on("play", () => setPlaying(true));
    wave.on("pause", () => setPlaying(false));
    wave.on("finish", () => setPlaying(false));
    wave.on("error", () => {
      if (active) latest.current.notify(latest.current.t("audioError"));
    });
    wave.load(sample.url, [sample.peaks], sample.duration).catch(() => {});
    return () => {
      active = false;
      wave.destroy();
      player.current = null;
    };
  }, [sample]);
  useEffect(() => {
    player.current?.setVolume(volume);
  }, [volume]);
  const toggle = () =>
    player.current?.playPause().catch(() => notify(t("audioError")));
  return (
    <footer className="player">
      <div className="now">
        <img className="cover" src="/art/record-sleeve.webp" alt="" />
        <div className="track-details">
          <strong title={track?.file_name}>
            {track?.file_name || t("waiting")}
          </strong>
          {track && (
            <small>
              {track.codec.toUpperCase()} ·{" "}
              {Math.round(track.sample_rate_hz / 100) / 10} kHz
            </small>
          )}
        </div>
      </div>
      <div className="transport">
        <Button
          variant="icon"
          disabled={index <= 0}
          onClick={() => select(index - 1)}
          aria-label={t("prev")}
        >
          <SkipBack />
        </Button>
        <Button
          className="play"
          onClick={toggle}
          disabled={!ready}
          aria-label={t(playing ? "pause" : "play")}
        >
          <span
            className="play-glyph"
            data-playing={playing}
            aria-hidden="true"
          >
            <Play fill="currentColor" />
            <Pause fill="currentColor" />
          </span>
        </Button>
        <Button
          variant="icon"
          disabled={!track || index >= tracks.length - 1}
          onClick={() => select(index + 1)}
          aria-label={t("next")}
        >
          <SkipForward />
        </Button>
      </div>
      <div className="timeline">
        {sample && <time>{clock(position)}</time>}
        <div
          className={"wave " + (!sample ? "wave-empty" : "")}
          ref={container}
          aria-hidden={sample ? undefined : true}
          {...(sample && {
            role: "slider",
            tabIndex: ready ? 0 : -1,
            "aria-disabled": !ready,
            "aria-label": t("seek"),
            "aria-valuemin": 0,
            "aria-valuemax": sample.duration,
            "aria-valuenow": Math.floor(position),
          })}
          onKeyDown={(e) => {
            if (ready && ["ArrowLeft", "ArrowRight"].includes(e.key)) {
              e.preventDefault();
              player.current.skip(e.key === "ArrowLeft" ? -5 : 5);
            }
          }}
        />
        {sample && <time>{clock(sample.duration)}</time>}
      </div>
      <label className="volume">
        <Volume2 />
        <input
          aria-label={t("volume")}
          type="range"
          min="0"
          max="1"
          step=".01"
          value={volume}
          onChange={(e) => setVolume(Number(e.target.value))}
        />
      </label>
    </footer>
  );
}
