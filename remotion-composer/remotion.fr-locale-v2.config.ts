/**
 * Configuration Remotion FR, version 2 (rendus en français uniquement).
 * Utilisation : npx remotion render ... --config=remotion.fr-locale-v2.config.ts
 *
 * Substitue au bundling les variantes .fr.tsx :
 *   - charts/BarChart, charts/PieChart : nombres au format français ;
 *   - HeroTitle : surlignage d'accent qui ne coupe jamais un mot.
 * Les fichiers d'origine ne sont pas modifiés ; remotion.fr-locale.config.ts (v1) reste
 * disponible et inchangé pour reproduire les rendus précédents.
 */
import { Config } from "@remotion/cli/config";
import webpack from "webpack";

const FR_VARIANTS = /[\\/](charts[\\/](BarChart|PieChart)|HeroTitle)$/;

Config.overrideWebpackConfig((current) => ({
  ...current,
  plugins: [
    ...(current.plugins ?? []),
    new webpack.NormalModuleReplacementPlugin(FR_VARIANTS, (resource) => {
      resource.request = `${resource.request}.fr`;
    }),
  ],
}));
