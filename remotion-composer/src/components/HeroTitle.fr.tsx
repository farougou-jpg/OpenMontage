import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

type HeroTitleProps = {
  title: string;
  subtitle?: string;
  /** Color of the leading accent characters and the underline. */
  accentColor?: string;
  /** Color of the remaining title characters. Pass the theme's textColor. */
  textColor?: string;
  /** Subtitle color. */
  subtitleColor?: string;
  /**
   * Scrim painted behind the title so it separates from whatever is underneath.
   * Defaults to a dark wash; a light theme must pass a light one, otherwise the
   * scrim darkens the backdrop and cancels out the theme's dark text.
   */
  scrimBackground?: string;
};

const DEFAULT_SCRIM =
  "radial-gradient(ellipse at center, rgba(15,23,42,0.35) 0%, rgba(15,23,42,0.55) 100%)";

export const HeroTitle: React.FC<HeroTitleProps> = ({
  title,
  subtitle,
  accentColor = "#22D3EE",
  textColor = "#F8FAFC",
  subtitleColor = "#A78BFA",
  scrimBackground = DEFAULT_SCRIM,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Staggered letter-by-letter spring
  const titleChars = title.split("");

  // Variante FR (rendus via remotion.fr-locale-v2.config.ts) : l'original colore les
  // 8 premiers caractères, ce qui coupe les mots (« Conçu po|ur »). Ici, si la limite
  // tombe au milieu d'un mot, on l'étend jusqu'à la fin de ce mot. Les titres d'un
  // seul mot (ex. « OpenMontage ») gardent le rendu d'origine à 8 caractères.
  const ORIGINAL_ACCENT = 8;
  let accentEnd = ORIGINAL_ACCENT;
  const midWord =
    title.includes(" ") &&
    title.length > ORIGINAL_ACCENT &&
    title[ORIGINAL_ACCENT - 1] !== " " &&
    title[ORIGINAL_ACCENT] !== " ";
  if (midWord) {
    const nextSpace = title.indexOf(" ", ORIGINAL_ACCENT);
    accentEnd = nextSpace === -1 ? title.length : nextSpace;
  }

  return (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        alignItems: "center",
        background: scrimBackground,
      }}
    >
      <div style={{ textAlign: "center", maxWidth: "85%" }}>
        {/* Main title with per-character spring */}
        <div
          style={{
            fontSize: 72,
            fontWeight: 800,
            fontFamily: "Space Grotesk, Inter, system-ui, sans-serif",
            lineHeight: 1.2,
            display: "flex",
            justifyContent: "center",
            flexWrap: "wrap",
            gap: 0,
          }}
        >
          {titleChars.map((char, i) => {
            const delay = i * 1.2;
            const charSpring = spring({
              frame: frame - delay,
              fps,
              config: { damping: 12, stiffness: 150 },
            });

            return (
              <span
                key={i}
                style={{
                  display: "inline-block",
                  opacity: charSpring,
                  transform: `translateY(${interpolate(charSpring, [0, 1], [30, 0])}px)`,
                  color: i < accentEnd ? accentColor : textColor, // Accent sans couper de mot
                  whiteSpace: char === " " ? "pre" : undefined,
                  minWidth: char === " " ? "0.3em" : undefined,
                }}
              >
                {char}
              </span>
            );
          })}
        </div>

        {/* Subtitle */}
        {subtitle && (
          <div
            style={{
              marginTop: 20,
              opacity: spring({
                frame: frame - titleChars.length * 1.2 - 5,
                fps,
                config: { damping: 20 },
              }),
              fontSize: 28,
              fontWeight: 400,
              color: subtitleColor,
              fontFamily: "Space Grotesk, Inter, system-ui, sans-serif",
              letterSpacing: "0.1em",
              textTransform: "uppercase",
            }}
          >
            {subtitle}
          </div>
        )}

        {/* Animated underline */}
        <div
          style={{
            margin: "24px auto 0",
            height: 3,
            backgroundColor: accentColor,
            borderRadius: 2,
            width: interpolate(
              spring({
                frame: frame - 15,
                fps,
                config: { damping: 15, stiffness: 60 },
              }),
              [0, 1],
              [0, 400]
            ),
          }}
        />
      </div>
    </AbsoluteFill>
  );
};
