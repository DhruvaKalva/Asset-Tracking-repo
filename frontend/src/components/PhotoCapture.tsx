/**
 * Condition photos for a handover: live camera, or files from disk.
 *
 * Photos are staged here and uploaded by the parent *after* the check-out or
 * check-in succeeds. That ordering matters: the rental does not exist until the
 * submission goes through, and a photo that cannot name its rental is evidence
 * of nothing.
 *
 * Every image is downscaled in the browser before it leaves. A modern phone
 * camera produces 4-8 MB per frame and five of those would push a handover past
 * the server's limit on a site connection, for detail nobody looks at.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { buttonClass } from "@/components/primitives";

/** The long edge every capture is reduced to. Enough to read a cracked panel. */
const MAX_EDGE = 1600;
const JPEG_QUALITY = 0.82;

export interface StagedPhoto {
  id: string;
  blob: Blob;
  /** Object URL for the thumbnail; revoked when the photo is dropped. */
  preview: string;
  name: string;
  source: "camera" | "file";
}

/** Shrink to MAX_EDGE and re-encode as JPEG. Never upscales a small image. */
async function downscale(input: Blob, name: string): Promise<Blob> {
  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(input);
  } catch {
    return input; // Not decodable here; let the server judge it.
  }

  const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height));
  const w = Math.max(1, Math.round(bitmap.width * scale));
  const h = Math.max(1, Math.round(bitmap.height * scale));

  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) return input;
  ctx.drawImage(bitmap, 0, 0, w, h);
  bitmap.close();

  const out = await new Promise<Blob | null>((resolve) =>
    canvas.toBlob(resolve, "image/jpeg", JPEG_QUALITY),
  );
  if (!out) return input;
  // Keep a filename on it so the audit trail shows something human.
  return new File([out], name.replace(/\.[^.]+$/, "") + ".jpg", { type: "image/jpeg" });
}

export function PhotoCapture({
  photos,
  onChange,
  disabled = false,
  showStrip = true,
}: {
  photos: StagedPhoto[];
  onChange: (next: StagedPhoto[]) => void;
  disabled?: boolean;
  /** Off when the parent renders the staged set itself, as the check-in
      comparison does -- two thumbnail strips of the same photos is noise. */
  showStrip?: boolean;
}) {
  const [cameraOn, setCameraOn] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const stopCamera = useCallback(() => {
    // Tracks must be stopped explicitly or the camera indicator stays lit
    // after the panel closes, which reads as the app still watching.
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setCameraOn(false);
  }, []);

  useEffect(() => stopCamera, [stopCamera]);

  async function startCamera() {
    setCameraError(null);
    if (!navigator.mediaDevices?.getUserMedia) {
      setCameraError("This browser has no camera API. Use Upload instead.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        // The rear camera on a phone; ignored by a laptop webcam.
        video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 } },
        audio: false,
      });
      streamRef.current = stream;
      setCameraOn(true);
      // The element only exists once cameraOn has rendered it.
      requestAnimationFrame(() => {
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          void videoRef.current.play();
        }
      });
    } catch (err) {
      const name = (err as DOMException)?.name;
      setCameraError(
        name === "NotAllowedError"
          ? "Camera permission was refused. Allow it in the browser's site settings, or use Upload."
          : name === "NotFoundError"
            ? "No camera found on this device. Use Upload instead."
            : name === "NotReadableError"
              ? "The camera is in use by another app."
              : "The camera could not be started. Use Upload instead.",
      );
      stopCamera();
    }
  }

  async function shoot() {
    const video = videoRef.current;
    if (!video || !video.videoWidth) return;
    setBusy(true);
    try {
      const canvas = document.createElement("canvas");
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      canvas.getContext("2d")?.drawImage(video, 0, 0);
      const raw = await new Promise<Blob | null>((resolve) =>
        canvas.toBlob(resolve, "image/jpeg", 0.95),
      );
      if (!raw) return;
      const name = `capture-${Date.now()}.jpg`;
      add(await downscale(raw, name), name, "camera");
    } finally {
      setBusy(false);
    }
  }

  function add(blob: Blob, name: string, source: StagedPhoto["source"]) {
    onChange([
      ...photos,
      { id: crypto.randomUUID(), blob, preview: URL.createObjectURL(blob), name, source },
    ]);
  }

  async function onFiles(e: React.ChangeEvent<HTMLInputElement>) {
    const picked = Array.from(e.target.files ?? []);
    if (picked.length === 0) return;
    setBusy(true);
    try {
      const shrunk = await Promise.all(picked.map((f) => downscale(f, f.name)));
      onChange([
        ...photos,
        ...shrunk.map((blob, i) => ({
          id: crypto.randomUUID(),
          blob,
          preview: URL.createObjectURL(blob),
          name: picked[i].name,
          source: "file" as const,
        })),
      ]);
    } finally {
      setBusy(false);
      e.target.value = ""; // so picking the same file twice still fires
    }
  }

  function remove(id: string) {
    const gone = photos.find((p) => p.id === id);
    if (gone) URL.revokeObjectURL(gone.preview);
    onChange(photos.filter((p) => p.id !== id));
  }

  const totalKb = Math.round(photos.reduce((sum, p) => sum + p.blob.size, 0) / 1024);

  return (
    <div className="space-y-2.5">
      <div className="flex flex-wrap items-center gap-2">
        {!cameraOn ? (
          <button type="button" onClick={startCamera} disabled={disabled} className={buttonClass}>
            📷 Take photo
          </button>
        ) : (
          <button type="button" onClick={stopCamera} className={buttonClass}>
            Close camera
          </button>
        )}

        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          disabled={disabled || busy}
          className={buttonClass}
        >
          ⤒ Upload files
        </button>

        <input
          ref={fileRef}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          multiple
          // On a phone this offers the camera directly; desktop ignores it.
          capture="environment"
          onChange={onFiles}
          className="hidden"
        />

        {photos.length > 0 && (
          <span className="text-[11px] text-ink-muted tnum">
            {photos.length} staged · {totalKb} KB
          </span>
        )}
        {busy && <span className="text-[11px] text-ink-muted">Processing…</span>}
      </div>

      {cameraError && (
        <p className="rounded-lg border border-warning/30 bg-warning/10 px-2.5 py-2 text-xs leading-snug text-warning">
          {cameraError}
        </p>
      )}

      {cameraOn && (
        <div className="overflow-hidden rounded-lg border border-hair bg-black">
          <video
            ref={videoRef}
            playsInline
            muted
            className="block max-h-64 w-full bg-black object-contain"
          />
          <div className="flex items-center justify-between gap-2 border-t border-hair bg-raised px-2.5 py-2">
            <span className="text-[11px] text-ink-muted">Frame the damage, then capture.</span>
            <button
              type="button"
              onClick={shoot}
              disabled={busy}
              className="rounded-lg bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40"
            >
              Capture
            </button>
          </div>
        </div>
      )}

      {showStrip && photos.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {photos.map((p) => (
            <li key={p.id} className="group relative">
              <img
                src={p.preview}
                alt={p.name}
                className="h-16 w-16 rounded-lg border border-hair object-cover"
              />
              <button
                type="button"
                onClick={() => remove(p.id)}
                aria-label={`Remove ${p.name}`}
                className="absolute -right-1.5 -top-1.5 grid h-5 w-5 place-items-center rounded-full border border-hair bg-surface text-xs leading-none text-ink-muted hover:text-critical"
              >
                ×
              </button>
              <span className="absolute bottom-0 left-0 rounded-br-lg rounded-tr-lg bg-black/60 px-1 text-[9px] text-white">
                {p.source === "camera" ? "cam" : "file"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
