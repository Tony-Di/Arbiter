import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { ConfigProvider, theme } from "antd";
import App from "./App";
import "./styles/tokens.css";
import "./styles/variant-b.css";

const FONT_SANS = '"IBM Plex Sans", ui-sans-serif, system-ui, sans-serif';

// antd dark theme tuned to the arbiter tokens. Hex approximations of the OKLCH
// surface/accent so antd's color algorithm (Tooltip, etc.) matches the design;
// the bespoke .vb-* CSS still drives the layout via the real OKLCH vars.
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ConfigProvider
      theme={{
        algorithm: theme.darkAlgorithm,
        token: {
          colorBgBase: "#1b1c20",
          colorPrimary: "#e6c25c",
          colorBgSpotlight: "#34353b",
          fontFamily: FONT_SANS,
          borderRadius: 6,
        },
      }}
    >
      <App split />
    </ConfigProvider>
  </StrictMode>,
);
