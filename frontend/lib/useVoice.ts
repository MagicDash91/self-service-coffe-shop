"use client";
import { useCallback, useRef, useState } from "react";

/** Push-to-talk recorder (MediaRecorder -> webm/opus blob). Auto-stops after maxMs. */
export function useRecorder(onDone: (blob: Blob) => void, maxMs = 12000) {
  const [recording, setRecording] = useState(false);
  const [level, setLevel] = useState(0);
  const rec = useRef<MediaRecorder | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  const raf = useRef<number>();

  const stop = useCallback(() => {
    clearTimeout(timer.current);
    if (raf.current) cancelAnimationFrame(raf.current);
    if (rec.current && rec.current.state !== "inactive") rec.current.stop();
    setRecording(false);
    setLevel(0);
  }, []);

  const start = useCallback(async () => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "";
    const r = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    const chunks: BlobPart[] = [];
    r.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    r.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      onDone(new Blob(chunks, { type: r.mimeType || "audio/webm" }));
    };
    // mic level meter for the pulsing ring
    const ctx = new AudioContext();
    const an = ctx.createAnalyser();
    ctx.createMediaStreamSource(stream).connect(an);
    const buf = new Uint8Array(an.fftSize);
    const tick = () => {
      an.getByteTimeDomainData(buf);
      let peak = 0;
      for (const v of buf) peak = Math.max(peak, Math.abs(v - 128));
      setLevel(peak / 128);
      raf.current = requestAnimationFrame(tick);
    };
    tick();
    r.addEventListener("stop", () => ctx.close());
    rec.current = r;
    r.start();
    setRecording(true);
    timer.current = setTimeout(stop, maxMs);
  }, [onDone, maxMs, stop]);

  return { recording, level, start, stop };
}

/** Plays TTS blobs one at a time; a new one interrupts the old. */
export function usePlayer() {
  const audio = useRef<HTMLAudioElement | null>(null);
  const [speaking, setSpeaking] = useState(false);
  const play = useCallback((blob: Blob) => {
    audio.current?.pause();
    const a = new Audio(URL.createObjectURL(blob));
    audio.current = a;
    a.onended = a.onpause = () => setSpeaking(false);
    setSpeaking(true);
    a.play().catch(() => setSpeaking(false));
  }, []);
  const cancel = useCallback(() => { audio.current?.pause(); setSpeaking(false); }, []);
  return { play, cancel, speaking };
}
