// Basemaps: Esri Canvas (Dark Gray / Light Gray), keyless.
//
// CARTO's public raster tiles now require an API key and otherwise stamp an
// "API KEY REQUIRED" watermark across every tile. Esri's Canvas basemaps are
// served without a key (the app already uses Esri World Imagery for the
// high-res satellite layer). Each theme is a base layer plus a transparent
// reference layer carrying place names and boundaries.
//
// The raster structure and the `imagery-ceiling` anchor are unchanged, so
// every data layer, the GIBS/Esri imagery overlays and the glyph stack keep
// behaving exactly as they did on CARTO.

const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas";
const ESRI_ATTRIBUTION = "Esri, HERE, Garmin, © OpenStreetMap contributors";

function esriCanvasStyle(theme: "Dark" | "Light") {
    const base = `esri-${theme.toLowerCase()}-gray`;
    const ref = `${base}-ref`;
    return {
        version: 8,
        glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
        sources: {
            [base]: {
                type: "raster",
                tiles: [`${ESRI}/World_${theme}_Gray_Base/MapServer/tile/{z}/{y}/{x}`],
                tileSize: 256,
                maxzoom: 16,
                attribution: ESRI_ATTRIBUTION,
            },
            [ref]: {
                type: "raster",
                tiles: [`${ESRI}/World_${theme}_Gray_Reference/MapServer/tile/{z}/{y}/{x}`],
                tileSize: 256,
                maxzoom: 16,
            },
        },
        layers: [
            { id: `${base}-layer`, type: "raster", source: base, minzoom: 0, maxzoom: 22 },
            // Imagery overlays (GIBS, Esri World Imagery) are inserted below this anchor,
            // so place names stay readable above them.
            { id: "imagery-ceiling", type: "background", paint: { "background-opacity": 0 } },
            { id: `${ref}-layer`, type: "raster", source: ref, minzoom: 0, maxzoom: 22 },
        ],
    };
}

export const darkStyle = esriCanvasStyle("Dark");
export const lightStyle = esriCanvasStyle("Light");
