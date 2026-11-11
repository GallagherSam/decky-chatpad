import {
  ButtonItem,
  DropdownItem,
  Field,
  PanelSection,
  PanelSectionRow,
  SliderField,
  ToggleField,
  staticClasses,
} from "@decky/ui";
import { callable, definePlugin, toaster } from "@decky/api";
import { useEffect, useMemo, useRef, useState } from "react";
import { FaKeyboard } from "react-icons/fa";
import { renderSVG } from "uqr";

interface LastSend {
  time: number;
  chars: number;
  preview: string;
  replaced: number;
  ok: boolean;
  error: string | null;
  duration: number;
}

interface IpInfo {
  iface: string;
  ip: string;
  kind: string;
}

interface Status {
  enabled: boolean;
  running: boolean;
  serverError: string | null;
  uinputOk: boolean;
  uinputError: string | null;
  ip: string;
  ips: IpInfo[];
  port: number;
  url: string;
  token: string;
  openKey: "enter" | "slash" | "none";
  keyDelayMs: number;
  openDelayMs: number;
  sends: number;
  lastSend: LastSend | null;
}

const getStatus = callable<[], Status>("get_status");
const setEnabled = callable<[enabled: boolean], Status>("set_enabled");
const rotateToken = callable<[], Status>("rotate_token");
const setSetting = callable<[key: string, value: unknown], Status>("set_setting");
const retryUinput = callable<[], Status>("retry_uinput");

const OPEN_KEY_OPTIONS = [
  { data: "enter", label: "Enter (WoW default)" },
  { data: "slash", label: "/ (only for /commands)" },
  { data: "none", label: "None (chat already open)" },
];

function ago(ts: number): string {
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  return `${Math.round(s / 3600)}h ago`;
}

function QrCode({ text }: { text: string }) {
  const src = useMemo(() => {
    const svg = renderSVG(text, { border: 2, pixelSize: 6, ecc: "M" });
    return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
  }, [text]);
  return (
    <div style={{ display: "flex", justifyContent: "center", padding: "6px 0" }}>
      <img src={src} style={{ width: 200, height: 200, imageRendering: "pixelated", borderRadius: 6 }} />
    </div>
  );
}

function Content() {
  const [st, setSt] = useState<Status | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [delay, setDelay] = useState<number | null>(null);
  const delayTimer = useRef<number | undefined>(undefined);

  const refresh = async () => {
    try {
      setSt(await getStatus());
      setErr(null);
    } catch (e) {
      setErr(String(e));
    }
  };

  useEffect(() => {
    refresh();
    const id = window.setInterval(refresh, 2000);
    return () => window.clearInterval(id);
  }, []);

  if (!st) {
    return (
      <PanelSection>
        <PanelSectionRow>
          <Field label={err ? "Backend error" : "Loading..."} description={err ?? undefined} />
        </PanelSectionRow>
      </PanelSection>
    );
  }

  const others = st.ips.filter((i) => i.ip !== st.ip);
  const last = st.lastSend;

  return (
    <>
      <PanelSection>
        <PanelSectionRow>
          <ToggleField
            label="Phone keyboard"
            description={st.running ? `Listening on port ${st.port}` : st.serverError ?? "Off"}
            checked={st.enabled}
            onChange={async (v) => setSt(await setEnabled(v))}
          />
        </PanelSectionRow>
        {!st.uinputOk && (
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              description={st.uinputError ?? "Virtual keyboard not created yet"}
              onClick={async () => setSt(await retryUinput())}
            >
              Retry virtual keyboard
            </ButtonItem>
          </PanelSectionRow>
        )}
      </PanelSection>

      {st.running && (
        <PanelSection title="Scan with your phone">
          <PanelSectionRow>
            <QrCode text={st.url} />
          </PanelSectionRow>
          <PanelSectionRow>
            <Field
              label={`${st.ip}:${st.port}`}
              description={
                <span style={{ wordBreak: "break-all", fontSize: 11 }}>
                  {st.url}
                  {others.length > 0 && (
                    <>
                      <br />
                      Also: {others.map((o) => `${o.ip} (${o.kind})`).join(", ")}
                    </>
                  )}
                </span>
              }
              bottomSeparator="none"
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              description="Disconnects any phone using the old link"
              onClick={async () => {
                setSt(await rotateToken());
                toaster.toast({ title: "Chatpad", body: "New pairing code. Rescan the QR." });
              }}
            >
              New pairing code
            </ButtonItem>
          </PanelSectionRow>
        </PanelSection>
      )}

      <PanelSection title="Last send">
        <PanelSectionRow>
          <Field
            label={last ? (last.ok ? `Typed ${last.chars} chars` : "Failed") : "Nothing yet"}
            description={
              last
                ? `${ago(last.time)}${last.ok ? ` in ${last.duration}s` : ""}: ${last.ok ? last.preview : last.error}` +
                  (last.replaced ? ` (${last.replaced} replaced with ?)` : "")
                : "Close this menu before sending; keys go to whatever has focus."
            }
          />
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Typing">
        <PanelSectionRow>
          <DropdownItem
            label="Open chat with"
            rgOptions={OPEN_KEY_OPTIONS}
            selectedOption={st.openKey}
            onChange={async (o) => setSt(await setSetting("open_key", o.data))}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <SliderField
            label="Key delay"
            description="Raise this if letters get dropped"
            value={delay ?? st.keyDelayMs}
            min={2}
            max={60}
            step={1}
            showValue
            valueSuffix=" ms"
            onChange={(v) => {
              setDelay(v);
              window.clearTimeout(delayTimer.current);
              delayTimer.current = window.setTimeout(async () => {
                setSt(await setSetting("key_delay_ms", v));
                setDelay(null);
              }, 400);
            }}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <SliderField
            label="Wait after opening chat"
            value={st.openDelayMs}
            min={0}
            max={500}
            step={20}
            showValue
            valueSuffix=" ms"
            onChange={async (v) => setSt(await setSetting("open_delay_ms", v))}
          />
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}

export default definePlugin(() => {
  return {
    name: "Chatpad",
    titleView: <div className={staticClasses.Title}>Chatpad</div>,
    content: <Content />,
    icon: <FaKeyboard />,
    onDismount() {},
  };
});
