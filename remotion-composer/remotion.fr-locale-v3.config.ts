/**
 * Configuration Remotion FR, version 3 (rendus en français uniquement).
 * Utilisation : npx remotion render ... --config=remotion.fr-locale-v3.config.ts
 *
 * Substitue au bundling les variantes .fr.tsx :
 *   - charts/BarChart, charts/PieChart : nombres au format français (v1) ;
 *   - HeroTitle : surlignage d'accent qui ne coupe jamais un mot (v2) ;
 *   - charts/KPIGrid : variations « 18,0 % » au lieu de « 18.0% » (v3) ;
 *   - ProgressBar : « 82 % » et libellé lisible sur fond sombre (v3).
 * Les fichiers d'origine ne sont pas modifiés ; les configurations v1 et v2 restent
 * disponibles et inchangées pour reproduire les rendus précédents.
 */
import { Config } from "@remotion/cli/config";
import webpack from "webpack";

const FR_VARIANTS = /[\\/](charts[\\/](BarChart|PieChart|KPIGrid)|HeroTitle|ProgressBar)$/;

Config.overrideWebpackConfig((current) => ({
  ...current,
  plugins: [
    ...(current.plugins ?? []),
    new webpack.NormalModuleReplacementPlugin(FR_VARIANTS, (resource) => {
      resource.request = `${resource.request}.fr`;
    }),
  ],
}));
