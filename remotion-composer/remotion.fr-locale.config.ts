/**
 * Configuration Remotion pour les rendus en français uniquement.
 * Utilisation : npx remotion render ... --config=remotion.fr-locale.config.ts
 *
 * Remplace, au moment du bundling, les graphiques par leurs variantes .fr.tsx
 * (format des nombres à la française). Les fichiers d'origine ne sont pas
 * modifiés et les rendus sans cette option restent inchangés.
 */
import { Config } from "@remotion/cli/config";
import webpack from "webpack";

const FR_CHARTS = /[\\/]charts[\\/](BarChart|PieChart)$/;

Config.overrideWebpackConfig((current) => ({
  ...current,
  plugins: [
    ...(current.plugins ?? []),
    new webpack.NormalModuleReplacementPlugin(FR_CHARTS, (resource) => {
      resource.request = `${resource.request}.fr`;
    }),
  ],
}));
