import { useEffect, useState } from "react";
import QRCode from "qrcode";

/** QR-Code wird lokal im Browser erzeugt (kein externer Dienst). */
export function QrCode({ text, label }: { text: string; label: string }) {
  const [url, setUrl] = useState<string>("");
  useEffect(() => {
    let alive = true;
    QRCode.toDataURL(text, { errorCorrectionLevel: "M", margin: 2, width: 320 })
      .then((u) => alive && setUrl(u))
      .catch(() => alive && setUrl(""));
    return () => {
      alive = false;
    };
  }, [text]);
  if (!url) return null;
  return <img className="qr" src={url} alt={label} width={320} height={320} />;
}
