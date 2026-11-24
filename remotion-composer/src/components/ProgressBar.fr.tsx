import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

type ProgressAnimationStyle = "fill" | "pulse" | "step";

interface ProgressSegment {
  value: number;
  color?: string;
  label?: string;
}

interface ProgressBarProps {
  progress: number;
  label?: string;
  color?: string;
  backgroundColor?: string;
  trackColor?: string;
  showPercentage?: boolean;
  animationStyle?: ProgressAnimationStyle;
  segments?: ProgressSegment[];
  height?: number;
  borderRadius?: number;
  fontFamily?: string;
  textColor?: string;
  labelFontSize?: number;
  percentageFontSize?: number;
}

export const ProgressBar: React.FC<ProgressBarProps> = ({
  progress,
  label,
  color = "#2563EB",
  backgroundColor = "#FFFFFF",
  trackColor = "#E5E7EB",
  showPercentage = true,
  animationStyle = "fill",
  segments,
  height = 32,
  borderRadius = 8,
  fontFamily = "Inter, system-ui, sans-serif",
  textColor = "#1F2937",
  labelFontSize = 36,
  percentageFontSize = 28,
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  // Variante FR (rendus via remotion.fr-locale-v3.config.ts) : Explainer ne transmet pas
  // textColor, si bien que le libellé (#1F2937 par défaut) devient illisible sur fond sombre.
  // Ici, seule la couleur par défaut du libellé s'adapte au fond. Valeurs, minutage et
  // animations sont identiques à l'original.
  const labelColor = textColor === "#1F2937" && isDark(backgroundColor) ? "#E2E8F0" : textColor;

  const clampedProgress = Math.max(0, Math.min(100, progress));

  // Container entrance animation
  const containerOpacity = spring({
    frame,
    fps,
    config: { damping: 20 },
  });
  const containerScale = spring({
    frame,
    fps,
    config: { damping: 15, stiffness: 100 },
    from: 0.95,
    to: 1,
  });

  // Build fill width based on animation style
  let fillFraction: number;

  if (animationStyle === "fill") {
    fillFraction = interpolate(
      frame,
      [10, Math.max(30, durationInFrames * 0.5)],
      [0, clampedProgress / 100],
      { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
    );
  } else if (animationStyle === "pulse") {
    const base = interpolate(
      frame,
      [10, Math.max(30, durationInFrames * 0.4)],
      [0, clampedProgress / 100],
      { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
    );
    // Subtle pulse once fill completes
    const pulsePhase = interpolate(
      frame,
      [durationInFrames * 0.4, durationInFrames * 0.9],
      [0, Math.PI * 4],
      { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
    );
    const pulseScale =
      base >= clampedProgress / 100 - 0.01
        ? 1 + Math.sin(pulsePhase) * 0.015
        : 1;
    fillFraction = base * pulseScale;
  } else {
    // step — discrete jumps
    const stepCount = segments ? segments.length : 5;
    const rawProgress = interpolate(
      frame,
      [10, Math.max(30, durationInFrames * 0.6)],
      [0, clampedProgress / 100],
      { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
    );
    fillFraction =
      Math.floor(rawProgress * stepCount) / stepCount;
  }

  // Percentage label spring (appears after fill starts)
  const percentOpacity = spring({
    frame: frame - 15,
    fps,
    config: { damping: 20 },
  });

  // Rendered percentage tracks fill
  const displayedPercent = Math.round(fillFraction * 100);

  // Segmented variant
  const isSegmented = segments && segments.length > 0;

  // Bar track dimensions (centered, 70% canvas width)
  const trackWidth = 1344; // 70% of 1920
  const trackLeft = (1920 - trackWidth) / 2;
  const trackTop = label ? 520 : 500;

  return (
    <AbsoluteFill
      style={{
        background: backgroundColor,
        justifyContent: "center",
        alignItems: "center",
      }}
    >
      <div
        style={{
          opacity: containerOpacity,
          transform: `scale(${containerScale})`,
          width: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 24,
        }}
      >
        {/* Label */}
        {label && (
          <div
            style={{
              fontFamily,
              fontWeight: 700,
              fontSize: labelFontSize,
              color: labelColor,
              textAlign: "center",
              opacity: spring({
                frame,
                fps,
                config: { damping: 20 },
              }),
            }}
          >
            {label}
          </div>
        )}

        {/* Track */}
        <div
          style={{
            width: `${(trackWidth / 1920) * 100}%`,
            position: "relative",
          }}
        >
          <div
            style={{
              width: "100%",
              height,
              backgroundColor: trackColor,
              borderRadius,
              overflow: "hidden",
              position: "relative",
              display: "flex",
            }}
          >
            {isSegmented ? (
              // Segmented bars
              segments!.map((seg, i) => {
                const segDelay = 10 + i * 8;
                const segProgress = spring({
                  frame: frame - segDelay,
                  fps,
                  config: { damping: 14, stiffness: 80 },
                });
                const segWidth = (seg.value / 100) * 100;
                return (
                  <div
                    key={i}
                    style={{
                      width: `${segWidth}%`,
                      height: "100%",
                      backgroundColor: seg.color || color,
                      transform: `scaleX(${segProgress})`,
                      transformOrigin: "left",
                      borderRight:
                        i < segments!.length - 1
                          ? `2px solid ${backgroundColor}`
                          : "none",
                    }}
                  />
                );
              })
            ) : (
              // Single fill bar
              <div
                style={{
                  width: `${fillFraction * 100}%`,
                  height: "100%",
                  backgroundColor: color,
                  borderRadius,
                  transition:
                    animationStyle === "step"
                      ? "width 0.15s ease"
                      : undefined,
                }}
              />
            )}
          </div>

          {/* Segment labels below track */}
          {isSegmented && (
            <div
              style={{
                display: "flex",
                width: "100%",
                marginTop: 8,
              }}
            >
              {segments!.map((seg, i) => {
                const segDelay = 10 + i * 8;
                const labelOp = spring({
                  frame: frame - segDelay - 6,
                  fps,
                  config: { damping: 20 },
                });
                return (
                  <div
                    key={i}
                    style={{
                      width: `${(seg.value / 100) * 100}%`,
                      fontFamily,
                      fontWeight: 500,
                      fontSize: 18,
                      color: labelColor,
                      textAlign: "center",
                      opacity: labelOp,
                    }}
                  >
                    {seg.label}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Percentage */}
        {showPercentage && !isSegmented && (
          <div
            style={{
              fontFamily,
              fontWeight: 800,
              fontSize: percentageFontSize,
              color,
              opacity: percentOpacity,
            }}
          >
            {displayedPercent}{" "}%
          </div>
        )}
      </div>
    </AbsoluteFill>
  );
};

/** Fond sombre ? (luminance relative < 0,4 ; couleurs #RRGGBB ou #RGB uniquement). */
function isDark(color: string): boolean {
  const m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(color.trim());
  if (!m) return false;
  const hex = m[1].length === 3 ? m[1].replace(/./g, (c) => c + c) : m[1];
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b < 0.4;
}
