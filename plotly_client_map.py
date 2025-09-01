import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import time
import json
import os
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
import hashlib
import numpy as np

# =========================
# Page Configuration
# =========================
st.set_page_config(
    page_title="Carte Interactive Clients & Sites",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# =========================
# Fonds de carte (basemaps) + helper
# =========================
BASEMAPS = {
    # Styles natifs Plotly/Mapbox - sans token et sans relief
    "OpenStreetMap":            {"type": "style",  "value": "open-street-map"},
    "Carto Positron":           {"type": "style",  "value": "carto-positron"},
    "Carto Darkmatter":         {"type": "style",  "value": "carto-darkmatter"},
    "Fond blanc":               {"type": "style",  "value": "white-bg"},
    # Tuiles raster superposées (toujours sans token)
    "Carto Voyager":            {"type": "raster", "value": "https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
                                 "attrib": "© OpenStreetMap, © CARTO"},
    "Positron (sans labels)":   {"type": "raster", "value": "https://a.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}.png",
                                 "attrib": "© OpenStreetMap, © CARTO"},
    "Darkmatter (sans labels)": {"type": "raster", "value": "https://a.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}.png",
                                 "attrib": "© OpenStreetMap, © CARTO"},
    "OSM France":               {"type": "raster", "value": "https://a.tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png",
                                 "attrib": "© OpenStreetMap France"},
    "OSM Humanitarian":         {"type": "raster", "value": "https://a.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png",
                                 "attrib": "© OpenStreetMap, HOT"},
    "Esri Light Gray":          {"type": "raster", "value": "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
                                 "attrib": "Tiles © Esri"},
    "Esri Imagerie (satellite)":{"type": "raster", "value": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                                 "attrib": "Imagery © Esri"}
}

def mapbox_kwargs(basemap_key: str, center_lat: float, center_lon: float, zoom: float):
    """Construit l'argument mapbox pour fig.update_layout selon le fond choisi."""
    bm = BASEMAPS.get(basemap_key, BASEMAPS["OpenStreetMap"])
    if bm["type"] == "style":
        return dict(
            mapbox=dict(
                accesstoken=None,
                style=bm["value"],
                center=dict(lat=center_lat, lon=center_lon),
                zoom=zoom,
            )
        )
    # Couche raster au-dessus d'un fond blanc neutre
    return dict(
        mapbox=dict(
            accesstoken=None,
            style="white-bg",
            center=dict(lat=center_lat, lon=center_lon),
            zoom=zoom,
            layers=[{
                "sourcetype": "raster",
                "source": [bm["value"]],
                "sourceattribution": bm.get("attrib", ""),
                "below": "traces"
            }],
        )
    )

# =========================
# Helpers
# =========================
class GeocodeCache:
    def __init__(self, cache_file='geocode_cache.json'):
        self.cache_file = cache_file
        self.cache = self.load_cache()
        self.geolocator = Nominatim(user_agent="client_map_ok_app", timeout=8)

    def load_cache(self):
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_cache(self):
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def geocode_address(self, address, code_postal=None):
        if address is None or (isinstance(address, float) and np.isnan(address)):
            return None, None
        address = str(address).strip()

        cp_part = ""
        if code_postal is not None and not (isinstance(code_postal, float) and np.isnan(code_postal)):
            cp_str = str(code_postal)
            import re as _re
            m = _re.search(r'(\d{4,5})', cp_str)
            if m:
                cp_part = m.group(1)

        full_address = f"{address}, {cp_part}, France" if cp_part else f"{address}, France"
        key = hashlib.md5(full_address.lower().encode()).hexdigest()

        if key in self.cache:
            coords = self.cache[key]
            return (coords['lat'], coords['lng']) if coords else (None, None)
        try:
            time.sleep(0.02)
            loc = self.geolocator.geocode(full_address, timeout=8)
            if loc:
                self.cache[key] = {'lat': loc.latitude, 'lng': loc.longitude}
                self.save_cache()
                return loc.latitude, loc.longitude
            # Fallback sans CP
            loc2 = self.geolocator.geocode(f"{address}, France", timeout=8)
            if loc2:
                self.cache[key] = {'lat': loc2.latitude, 'lng': loc2.longitude}
                self.save_cache()
                return loc2.latitude, loc2.longitude
            self.cache[key] = None
            self.save_cache()
            return None, None
        except Exception:
            self.cache[key] = None
            self.save_cache()
            return None, None

@st.cache_resource
def get_geocode_cache():
    return GeocodeCache()

def load_site_addresses():
    """
    Charge les adresses des sites depuis /mnt/data/villes-afe.docx si dispo,
    sinon une liste de secours.
    """
    path = "/mnt/data/villes-afe.docx"
    text = ""
    try:
        from docx import Document  # type: ignore
        if os.path.exists(path):
            doc = Document(path)
            lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
            text = "\n".join(lines)
    except Exception:
        pass
    if not text:
        text = """85 avenue clément ader 34170 castelnau-le-lez
335 chemin bas du mas de boudan Nîmes
10 rue roger broussoux 30170 saint hyppolyte du fort
74 rue de candiac 30600 vauvert
1026 route de Nimes 30700 uzes
27 rue des muriers 07150 vallon pont d'arc
1 rue des pénitents 04310 Peyruis
5 rue deleuze 04200 sisteron
5 allee jean perrin 13270 fos sur mer
116 rue marc seguin 07503 guilherand granges
chemin des alpilles 04000 dignes les bains
45 rue merlot 34130 Mauguio
95 avenue des logissons 13770 venelles
7 allee de la passe pierre 13800 istres
235 avenue des costières 30800 saint gilles
88 avenue gaston baissette 34400 lunel"""
    addrs = []
    for line in [l.strip() for l in text.splitlines() if l.strip()]:
        if ":" in line:
            line = line.split(":")[-1].strip()
        if "France" not in line:
            line = line + ", France"
        addrs.append(line)
    # dédoublonnage
    seen, out = set(), []
    for a in addrs:
        k = a.lower()
        if k not in seen:
            seen.add(k)
            out.append(a)
    return out

# =========================
# Data processing
# =========================
@st.cache_data
def process_excel_data(file):
    try:
        df = pd.read_excel(file, engine='openpyxl')
    except Exception:
        df = pd.read_excel(file)
    df.columns = df.columns.str.strip()

    # Mapping heuristique
    cmap = {}
    for c in df.columns:
        cl = c.lower().replace('_', ' ').replace('-', ' ')
        if any(k in cl for k in ['nom', 'client', 'entreprise', 'raison sociale']):
            cmap.setdefault('nom_client', c)
        if any(k in cl for k in ['ville', 'city', 'commune']):
            cmap.setdefault('ville', c)
        if any(k in cl for k in ['code postal', 'cp', 'postal', 'zip']):
            cmap.setdefault('code_postal', c)
        if any(k in cl for k in ['adresse', 'address', 'voie']):
            cmap.setdefault('adresse', c)
        if any(k in cl for k in ['responsable', 'manager']):
            cmap.setdefault('responsable', c)
        if any(k in cl for k in ['collaborateur', 'commercial']):
            cmap.setdefault('collaborateur', c)
        if any(k in cl for k in ['activité', 'secteur', 'activity']):
            cmap.setdefault('activite', c)
        if any(k in cl for k in ['forme juri', 'forme', 'juridique', 'type']):
            cmap.setdefault('forme', c)
        if 'site' in cl:
            cmap.setdefault('site', c)
        if any(k in cl for k in ['code dossier', 'dossier', 'code', 'num dossier', 'numero dossier']):
            cmap.setdefault('code_dossier', c)
    print("Colonnes détectées:", cmap)
    return df, cmap

def apply_sidebar_filters(df, cmap):
    """Applique les filtres de la sidebar et retourne df filtré + dict des sélections."""
    filters_selected = {}

    if 'ville' in cmap and cmap['ville'] in df.columns:
        villes = sorted(df[cmap['ville']].dropna().astype(str).unique())
        sel = st.sidebar.multiselect("Ville", villes)
        if sel:
            df = df[df[cmap['ville']].astype(str).isin(sel)]
            filters_selected['ville'] = sel

    if 'code_postal' in cmap and cmap['code_postal'] in df.columns:
        cps = sorted(df[cmap['code_postal']].dropna().astype(str).unique())
        sel = st.sidebar.multiselect("Code postal", cps)
        if sel:
            df = df[df[cmap['code_postal']].astype(str).isin(sel)]
            filters_selected['code_postal'] = sel

    if 'site' in cmap and cmap['site'] in df.columns:
        sites = sorted(df[cmap['site']].dropna().astype(str).unique())
        sel = st.sidebar.multiselect("Site", sites)
        if sel:
            df = df[df[cmap['site']].astype(str).isin(sel)]
            filters_selected['site'] = sel

    if 'responsable' in cmap and cmap['responsable'] in df.columns:
        responsables = sorted(df[cmap['responsable']].dropna().astype(str).unique())
        sel = st.sidebar.multiselect("Responsable", responsables)
        if sel:
            df = df[df[cmap['responsable']].astype(str).isin(sel)]
            filters_selected['responsable'] = sel

    if 'collaborateur' in cmap and cmap['collaborateur'] in df.columns:
        collabs = sorted(df[cmap['collaborateur']].dropna().astype(str).unique())
        sel = st.sidebar.multiselect("Collaborateur", collabs)
        if sel:
            df = df[df[cmap['collaborateur']].astype(str).isin(sel)]
            filters_selected['collaborateur'] = sel

    if 'activite' in cmap and cmap['activite'] in df.columns:
        acts = sorted(df[cmap['activite']].dropna().astype(str).unique())
        sel = st.sidebar.multiselect("Secteur d'activité", acts)
        if sel:
            df = df[df[cmap['activite']].astype(str).isin(sel)]
            filters_selected['activite'] = sel

    if 'forme' in cmap and cmap['forme'] in df.columns:
        formes = sorted(df[cmap['forme']].dropna().astype(str).unique())
        sel = st.sidebar.multiselect("Forme juridique", formes)
        if sel:
            df = df[df[cmap['forme']].astype(str).isin(sel)]
            filters_selected['forme'] = sel

    if 'code_dossier' in cmap and cmap['code_dossier'] in df.columns:
        codes = sorted(df[cmap['code_dossier']].dropna().astype(str).unique())
        sel = st.sidebar.multiselect("Code dossier", codes)
        if sel:
            df = df[df[cmap['code_dossier']].astype(str).isin(sel)]
            filters_selected['code_dossier'] = sel

    if 'nom_client' in cmap and cmap['nom_client'] in df.columns:
        q = st.sidebar.text_input("Nom client contient…")
        if q:
            df = df[df[cmap['nom_client']].astype(str).str.contains(q, case=False, na=False)]
            filters_selected['nom_contains'] = q

    if st.sidebar.button("🔄 Réinitialiser les filtres"):
        st.experimental_rerun()

    return df, filters_selected

# =========================
# Map creation
# =========================
def create_map(df, cmap, geocache, basemap_key: str):
    if 'ville' not in cmap:
        st.error("Aucune colonne 'ville' détectée.")
        return None, None

    ville_col = cmap['ville']
    cp_col = cmap.get('code_postal')
    code_dossier_col = cmap.get('code_dossier')

    counts = {}
    clients_per_key = {}
    codes_dossier_per_key = {}

    for _, row in df.iterrows():
        ville = row.get(ville_col, None)
        if pd.isna(ville) or str(ville).strip() == "":
            continue
        cp = row.get(cp_col, None) if cp_col and cp_col in df.columns else None
        key = (str(ville).strip(), str(cp).strip() if cp is not None and not pd.isna(cp) else None)
        counts[key] = counts.get(key, 0) + 1

        if key not in clients_per_key:
            clients_per_key[key] = []
            codes_dossier_per_key[key] = set()

        client_name = "Client"
        if 'nom_client' in cmap and cmap['nom_client'] in df.columns:
            client_name = str(row.get(cmap['nom_client'], "Client"))

        code_dossier = ""
        if code_dossier_col and code_dossier_col in df.columns:
            code_doss = row.get(code_dossier_col, "")
            if not pd.isna(code_doss) and str(code_doss).strip():
                code_dossier = str(code_doss).strip()
                codes_dossier_per_key[key].add(code_dossier)

        clients_per_key[key].append({'nom': client_name, 'code_dossier': code_dossier})

    def get_color_by_count(nb_clients):
        if nb_clients <= 10:   return 'rgba(0, 128, 0, 0.7)'
        if nb_clients <= 49:   return 'rgba(50, 130, 184, 0.7)'
        if nb_clients <= 100:  return 'rgba(255, 140, 0, 0.7)'
        return 'rgba(255, 0, 0, 0.7)'

    def get_category_by_count(nb_clients):
        if nb_clients <= 10:   return "Faible (1-10)"
        if nb_clients <= 49:   return "Moyen (11-49)"
        if nb_clients <= 100:  return "Élevé (50-100)"
        return "Très élevé (100+)"

    map_rows = []
    done = 0
    total = len(counts)
    if total == 0:
        return None, None
    prog = st.progress(0)

    for (ville, cp), nb in counts.items():
        done += 1
        prog.progress(done/total)
        lat, lon = geocache.geocode_address(ville, cp)
        if not (lat and lon):
            continue

        display = f"{ville}" + (f" ({cp})" if cp else "")
        hover = f"<b>{display}</b><br>Nombre de clients: {nb}<br>Catégorie: {get_category_by_count(nb)}<br><br>"

        if clients_per_key.get((ville, cp)):
            clients = clients_per_key[(ville, cp)][:15]
            for client in clients:
                if client['code_dossier']:
                    hover += f"• {client['nom']} ({client['code_dossier']})<br>"
                else:
                    hover += f"• {client['nom']}<br>"
            if len(clients_per_key[(ville, cp)]) > 15:
                hover += f"... et {len(clients_per_key[(ville, cp)])-15} autres<br>"

        map_rows.append({
            'ville': ville,
            'cp': cp or "",
            'lat': lat,
            'lon': lon,
            'nb': nb,
            'hover': hover,
            'color': get_color_by_count(nb),
            'category': get_category_by_count(nb)
        })
    prog.empty()

    if not map_rows:
        st.warning("Aucune ville géocodée.")
        return None, None

    mdf = pd.DataFrame(map_rows)
    fig = go.Figure()

    categories = mdf['category'].unique()
    color_map = {
        "Faible (1-10)": 'rgba(0, 128, 0, 0.7)',
        "Moyen (11-49)": 'rgba(50, 130, 184, 0.7)',
        "Élevé (50-100)": 'rgba(255, 140, 0, 0.7)',
        "Très élevé (100+)": 'rgba(255, 0, 0, 0.7)'
    }

    for category in sorted(categories):
        cat_data = mdf[mdf['category'] == category]
        if not cat_data.empty:
            fig.add_trace(go.Scattermapbox(
                lat=cat_data['lat'],
                lon=cat_data['lon'],
                mode='markers',
                marker=dict(
                    size=np.clip(cat_data['nb']*3, 8, 50),
                    color=color_map[category],
                    opacity=0.8
                ),
                text=cat_data['hover'],
                hovertemplate='%{text}<extra></extra>',
                name=f'Clients {category}'
            ))

    if st.sidebar.checkbox("Afficher les sites (cibles rouges)", value=True):
        site_points = []
        for addr in load_site_addresses():
            s_lat, s_lon = geocache.geocode_address(addr)
            if s_lat and s_lon:
                site_points.append((s_lat, s_lon, addr))
        if site_points:
            lats = [x[0] for x in site_points]
            lons = [x[1] for x in site_points]
            texts = [x[2] for x in site_points]
            fig.add_trace(go.Scattermapbox(
                lat=lats, lon=lons, mode='markers',
                marker=dict(size=22, color="rgba(255,0,0,0.20)", opacity=0.9, symbol="circle"),
                text=texts, hovertemplate="<b>%{text}</b><extra>Site</extra>", name="Sites (zone)"
            ))
            fig.add_trace(go.Scattermapbox(
                lat=lats, lon=lons, mode='markers',
                marker=dict(size=8, color="red", symbol="circle"),
                text=texts, hovertemplate="<b>%{text}</b><extra>Site</extra>", name="Sites"
            ))

    center_lat = mdf['lat'].mean()
    center_lon = mdf['lon'].mean()
    fig.update_layout(
        **mapbox_kwargs(basemap_key, center_lat, center_lon, 6),
        height=600, margin=dict(t=0, b=0, l=0, r=0), showlegend=True, dragmode='pan'
    )
    return fig, mdf

# =========================
# Proximity Analysis
# =========================
def analyze_proximity(df_filtered, cmap, geocache, radius_km=50):
    if 'ville' not in cmap:
        return None, None

    site_coords = []
    site_addresses = load_site_addresses()
    for addr in site_addresses:
        lat, lon = geocache.geocode_address(addr)
        if lat and lon:
            site_coords.append({'adresse': addr, 'lat': lat, 'lon': lon})

    if not site_coords:
        return None, None

    ville_col = cmap['ville']
    cp_col = cmap.get('code_postal')

    client_groups = {}
    for _, row in df_filtered.iterrows():
        ville = row.get(ville_col, None)
        if pd.isna(ville) or str(ville).strip() == "":
            continue
        cp = row.get(cp_col, None) if cp_col and cp_col in df_filtered.columns else None
        key = (str(ville).strip(), str(cp).strip() if cp is not None and not pd.isna(cp) else None)
        client_groups[key] = client_groups.get(key, 0) + 1

    proximity_data, zones_sans_site = [], []
    for (ville, cp), nb_clients in client_groups.items():
        client_lat, client_lon = geocache.geocode_address(ville, cp)
        if not (client_lat and client_lon):
            continue

        min_distance = float('inf')
        closest_site = None
        for site in site_coords:
            distance = geodesic((client_lat, client_lon), (site['lat'], site['lon'])).kilometers
            if distance < min_distance:
                min_distance = distance
                closest_site = site

        within_radius = min_distance <= radius_km
        data_point = {
            'ville': ville, 'cp': cp or "", 'lat': client_lat, 'lon': client_lon,
            'nb_clients': nb_clients, 'site_proche': closest_site['adresse'] if closest_site else "",
            'distance_km': round(min_distance, 1), 'dans_rayon': within_radius
        }
        (proximity_data if within_radius else zones_sans_site).append(data_point)

    return proximity_data, zones_sans_site

def create_proximity_map(proximity_data, zones_sans_site, geocache, radius_km=50, basemap_key: str = "OpenStreetMap"):
    fig = go.Figure()

    site_coords = []
    for addr in load_site_addresses():
        lat, lon = geocache.geocode_address(addr)
        if lat and lon:
            site_coords.append((lat, lon, addr))

    if site_coords:
        site_lats = [x[0] for x in site_coords]
        site_lons = [x[1] for x in site_coords]
        site_texts = [x[2] for x in site_coords]

        for lat, lon, _ in site_coords:
            radius_deg = radius_km / 111.0
            theta = np.linspace(0, 2*np.pi, 100)
            circle_lats = lat + radius_deg * np.cos(theta)
            circle_lons = lon + radius_deg * np.sin(theta)
            fig.add_trace(go.Scattermapbox(
                lat=circle_lats, lon=circle_lons, mode='lines',
                line=dict(color='red', width=2), showlegend=False, hoverinfo='skip'
            ))

        fig.add_trace(go.Scattermapbox(
            lat=site_lats, lon=site_lons, mode='markers',
            marker=dict(size=15, color='red', symbol='circle'),
            text=site_texts, hovertemplate="<b>Site:</b> %{text}<extra></extra>",
            name=f'Sites (rayon {radius_km}km)'
        ))

    if proximity_data:
        prox_df = pd.DataFrame(proximity_data)
        fig.add_trace(go.Scattermapbox(
            lat=prox_df['lat'], lon=prox_df['lon'], mode='markers',
            marker=dict(size=np.clip(prox_df['nb_clients']*2+8, 10, 40), color='green', opacity=0.7),
            text=[f"<b>{row['ville']}</b><br>Clients: {row['nb_clients']}<br>Site proche: {row['site_proche']}<br>Distance: {row['distance_km']} km"
                  for _, row in prox_df.iterrows()],
            hovertemplate='%{text}<extra></extra>',
            name=f'Clients proches (<{radius_km}km)'
        ))

    if zones_sans_site:
        zones_df = pd.DataFrame(zones_sans_site)
        fig.add_trace(go.Scattermapbox(
            lat=zones_df['lat'], lon=zones_df['lon'], mode='markers',
            marker=dict(size=np.clip(zones_df['nb_clients']*2+8, 10, 40), color='orange', opacity=0.8),
            text=[f"<b>{row['ville']}</b><br>Clients: {row['nb_clients']}<br>Site le plus proche: {row['site_proche']}<br>Distance: {row['distance_km']} km"
                  for _, row in zones_df.iterrows()],
            hovertemplate='%{text}<extra></extra>',
            name=f'Zones sans site (>{radius_km}km)'
        ))

    all_lats, all_lons = [], []
    if site_coords:
        all_lats.extend([x[0] for x in site_coords]); all_lons.extend([x[1] for x in site_coords])
    if proximity_data:
        all_lats.extend([x['lat'] for x in proximity_data]); all_lons.extend([x['lon'] for x in proximity_data])
    if zones_sans_site:
        all_lats.extend([x['lat'] for x in zones_sans_site]); all_lons.extend([x['lon'] for x in zones_sans_site])

    center_lat = np.mean(all_lats) if all_lats else 44.0
    center_lon = np.mean(all_lons) if all_lons else 4.0

    fig.update_layout(
        **mapbox_kwargs(basemap_key, center_lat, center_lon, 6),
        height=700, margin=dict(t=20, b=0, l=0, r=0), showlegend=True, dragmode='pan'
    )
    return fig

# =========================
# Concentration
# =========================
def analyze_concentration(df, cmap, geocache):
    if 'ville' not in cmap:
        return None

    vcol = cmap['ville']
    df = df.copy()
    df[vcol] = df[vcol].astype(str).str.strip()
    cpcol = cmap.get('code_postal')
    if cpcol and cpcol in df.columns:
        import re as _re
        df[cpcol] = df[cpcol].astype(str)
        df[cpcol] = df[cpcol].str.extract(r'(\d{4,5})', expand=False)

    if cpcol and cpcol in df.columns:
        grp = df.groupby([vcol, cpcol]).size().reset_index(name='count')
    else:
        grp = df.groupby([vcol]).size().reset_index(name='count')
        grp[cpcol or 'code_postal'] = ""

    rows_input = len(df)
    total_groups = len(grp)
    geocoded = 0
    failed_groups = []

    rows = []
    for _, r in grp.iterrows():
        ville = r[vcol]
        cp = r[cpcol] if (cpcol and cpcol in r) else ""
        count = int(r['count'])
        lat, lon = geocache.geocode_address(ville, cp if cp else None)
        if not (lat and lon) and cp:
            lat, lon = geocache.geocode_address(ville, None)
        if lat and lon:
            geocoded += 1
            rows.append({'ville': ville, 'cp': cp or "", 'nb': count, 'lat': lat, 'lon': lon})
        else:
            failed_groups.append({'ville': str(ville), 'code_postal': str(cp or ""), 'nb_clients': count})

    if not rows:
        return None

    vdf = pd.DataFrame(rows)
    q25, q50, q75, q90 = [float(vdf['nb'].quantile(q)) for q in (0.25, 0.5, 0.75, 0.90)]
    def cat(n):
        if n >= q90: return "Très Forte (>90e)"
        if n >= q75: return "Forte (75-90e)"
        if n >= q50: return "Moyenne (50-75e)"
        if n >= q25: return "Faible (25-50e)"
        return "Très Faible (<25e)"
    vdf['categorie'] = vdf['nb'].apply(cat)

    diag = {
        'rows_input': rows_input,
        'groups_total': total_groups,
        'groups_geocoded': geocoded,
        'groups_dropped': max(total_groups - geocoded, 0),
        'failed_groups': failed_groups
    }
    return vdf, diag

def concentration_map(vdf, basemap_key: str = "OpenStreetMap"):
    fig = go.Figure()
    color_map = {
        "Très Forte (>90e)": '#8B0000',
        "Forte (75-90e)": '#FF0000',
        "Moyenne (50-75e)": '#FF8C00',
        "Faible (25-50e)": '#FFD700',
        "Très Faible (<25e)": '#90EE90'
    }
    for cat, col in color_map.items():
        sub = vdf[vdf['categorie'] == cat]
        if sub.empty:
            continue
        fig.add_trace(go.Scattermapbox(
            lat=sub['lat'], lon=sub['lon'], mode='markers',
            marker=dict(size=np.clip(sub['nb']*0.8+10, 10, 30), color=col, opacity=0.85),
            text=[f"<b>{row['ville']}</b><br>{row['cp']}<br>{row['nb']} clients" for _, row in sub.iterrows()],
            hovertemplate='%{text}<extra></extra>', name=cat
        ))
    center_lat = vdf['lat'].mean()
    center_lon = vdf['lon'].mean()
    fig.update_layout(
        **mapbox_kwargs(basemap_key, center_lat, center_lon, 6),
        height=700, margin=dict(t=20, b=0, l=0, r=0), showlegend=True, dragmode='pan'
    )
    return fig

# =========================
# UI
# =========================
def main():
    st.title("🗺️ Carte Interactive Clients & Sites")

    col1, col2 = st.columns([3,1])
    with col1:
        uploaded = st.file_uploader("📄 Importer votre fichier Excel clients", type=['xlsx','xls'])
    with col2:
        if st.button("🔄 Vider le cache"):
            st.cache_data.clear()
            st.cache_resource.clear()
            st.success("Cache vidé.")
            st.experimental_rerun()

    if not uploaded:
        st.info("Importez un fichier Excel pour démarrer.")
        return

    with st.spinner("Lecture du fichier…"):
        df, cmap = process_excel_data(uploaded)
    if df is None or df.empty:
        st.error("Fichier vide ou illisible.")
        return
    st.success(f"{len(df)} enregistrements chargés.")

    with st.expander("🔍 Colonnes détectées dans le fichier"):
        st.write("**Toutes les colonnes du fichier:**", list(df.columns))
        st.write("**Correspondances détectées:**", cmap)
        if 'code_dossier' in cmap:
            st.success(f"✅ Colonne code_dossier détectée: {cmap['code_dossier']}")
        else:
            st.warning("⚠️ Aucune colonne code_dossier détectée automatiquement")

    # ---- Sélecteur de fond de carte ----
    st.sidebar.header("🗺️ Fond de carte")
    basemap_key = st.sidebar.selectbox(
        "Style",
        list(BASEMAPS.keys()),
        index=list(BASEMAPS.keys()).index("OpenStreetMap"),
        help="Vues neutres sans relief. Les entrées 'raster' ne nécessitent pas de token."
    )

    st.sidebar.header("🔍 Filtres")
    df_filtered, _ = apply_sidebar_filters(df, cmap)
    st.caption(f"🔎 {len(df_filtered)} enregistrements après filtres.")

    geocache = get_geocode_cache()
    with st.spinner("Création de la carte…"):
        fig, map_df = create_map(df_filtered, cmap, geocache, basemap_key)
    if fig is None:
        st.warning("Aucune donnée à cartographier après filtres.")
        return
    st.plotly_chart(fig, use_container_width=True, config={
        'displaylogo': False,
        'modeBarButtonsToRemove': [],
        'displayModeBar': True,
        'scrollZoom': True,
        'doubleClick': 'reset+autosize'
    })

    # Liste clients
    st.subheader("📋 Liste des clients (après filtres)")
    cols_to_show, col_labels = [], []
    for logical, label in [
        ('nom_client','Nom'), ('ville','Ville'), ('code_postal','Code postal'),
        ('code_dossier','Code dossier'), ('responsable','Responsable'),
        ('collaborateur','Collaborateur'), ('activite',"Secteur d'activité"),
        ('forme','Forme juridique'), ('site','Site'), ('adresse','Adresse'),
    ]:
        c = cmap.get(logical)
        if c and c in df_filtered.columns:
            cols_to_show.append(c); col_labels.append(label)

    if cols_to_show:
        disp = df_filtered[cols_to_show].copy()
        disp.columns = col_labels
        sort_cols = [col for col in ['Ville','Nom'] if col in disp.columns]
        if sort_cols:
            disp = disp.sort_values(sort_cols, kind='stable')
        st.dataframe(disp, use_container_width=True)
        csv = disp.to_csv(index=False, sep=';').encode('utf-8')
        st.download_button("💾 Exporter la liste (CSV)", data=csv, file_name="clients_filtres.csv", mime="text/csv")
    else:
        st.info("Aucune colonne standard à afficher (nom, ville, etc.).")

    # ---- Analyse de proximité ----
    st.markdown("---")
    st.header("🎯 Analyse de Proximité Sites/Clients")
    col1, col2 = st.columns([2, 1])
    with col1:
        st.write("Analysez la concentration de clients autour des sites existants et identifiez les zones d'opportunité.")
    with col2:
        radius_km = st.slider("Rayon d'analyse (km)", min_value=10, max_value=100, value=50, step=10)

    if st.button("🎯 Lancer l'analyse de proximité"):
        with st.spinner("Analyse en cours..."):
            proximity_data, zones_sans_site = analyze_proximity(df_filtered, cmap, geocache, radius_km)

        if proximity_data is None and zones_sans_site is None:
            st.warning("Impossible de réaliser l'analyse (aucun site géocodé).")
            return

        col1, col2, col3, col4 = st.columns(4)
        nb_clients_proches = sum(x['nb_clients'] for x in proximity_data) if proximity_data else 0
        nb_clients_eloignes = sum(x['nb_clients'] for x in zones_sans_site) if zones_sans_site else 0
        nb_villes_proches = len(proximity_data) if proximity_data else 0
        nb_villes_eloignees = len(zones_sans_site) if zones_sans_site else 0

        with col1:
            st.metric("Clients proches des sites", nb_clients_proches, f"{nb_villes_proches} villes")
        with col2:
            st.metric("Clients éloignés des sites", nb_clients_eloignes, f"{nb_villes_eloignees} villes")
        with col3:
            total_clients = nb_clients_proches + nb_clients_eloignes
            pct_proches = round(nb_clients_proches/total_clients*100, 1) if total_clients > 0 else 0
            st.metric("% clients couverts", f"{pct_proches}%")
        with col4:
            pct_zones = round(nb_villes_eloignees/(nb_villes_proches + nb_villes_eloignees)*100, 1) if (nb_villes_proches + nb_villes_eloignees) > 0 else 0
            st.metric("% zones sans couverture", f"{pct_zones}%")

        prox_fig = create_proximity_map(proximity_data, zones_sans_site, geocache, radius_km, basemap_key)
        st.plotly_chart(prox_fig, use_container_width=True, config={
            'displaylogo': False,
            'modeBarButtonsToRemove': [],
            'displayModeBar': True,
            'scrollZoom': True,
            'doubleClick': 'reset+autosize'
        })

        col1, col2 = st.columns(2)
        with col1:
            st.subheader("🟢 Zones bien couvertes")
            if proximity_data:
                prox_df = pd.DataFrame(proximity_data).sort_values('nb_clients', ascending=False)
                prox_display = prox_df[['ville', 'cp', 'nb_clients', 'distance_km', 'site_proche']].rename(
                    columns={'ville':'Ville','cp':'CP','nb_clients':'Nb Clients','distance_km':'Distance (km)','site_proche':'Site le plus proche'})
                st.dataframe(prox_display, use_container_width=True)
                st.download_button("💾 Exporter zones couvertes",
                    data=prox_display.to_csv(index=False, sep=';').encode('utf-8'),
                    file_name="zones_couvertes.csv", mime="text/csv")
            else:
                st.info("Aucune zone couverte dans le rayon défini.")
        with col2:
            st.subheader("🟠 Zones d'opportunité")
            if zones_sans_site:
                zones_df = pd.DataFrame(zones_sans_site).sort_values('nb_clients', ascending=False)
                zones_display = zones_df[['ville', 'cp', 'nb_clients', 'distance_km', 'site_proche']].rename(
                    columns={'ville':'Ville','cp':'CP','nb_clients':'Nb Clients','distance_km':'Distance (km)','site_proche':'Site le plus proche'})
                st.dataframe(zones_display, use_container_width=True)
                st.download_button("💾 Exporter zones d'opportunité",
                    data=zones_display.to_csv(index=False, sep=';').encode('utf-8'),
                    file_name="zones_opportunite.csv", mime="text/csv")
            else:
                st.info("Toutes les zones sont couvertes dans le rayon défini.")

    # ---- Analyse de concentration ----
    st.markdown("---")
    st.header("📊 Analyse de concentration")
    if st.button("🔍 Lancer l'analyse"):
        with st.spinner("Analyse en cours…"):
            res = analyze_concentration(df_filtered, cmap, geocache)
        if not res:
            st.warning("Impossible de créer la carte de concentration (aucun groupe géocodé).")
            return
        vdf, diag = res
        st.caption(f"🔧 Diagnostic: {diag['rows_input']} lignes • {diag['groups_total']} groupes • "
                   f"{diag['groups_geocoded']} géocodés • {diag['groups_dropped']} non géocodés")
        if diag.get('failed_groups'):
            with st.expander("Voir les groupes non géocodés"):
                fg = pd.DataFrame(diag['failed_groups']).rename(
                    columns={'ville':'Ville','code_postal':'Code postal','nb_clients':'Nombre de clients'})
                st.dataframe(fg, use_container_width=True)

        cfig = concentration_map(vdf, basemap_key)
        st.plotly_chart(cfig, use_container_width=True, config={
            'displaylogo': False,
            'modeBarButtonsToRemove': [],
            'displayModeBar': True,
            'scrollZoom': True,
            'doubleClick': 'reset+autosize'
        })

if __name__ == "__main__":
    main()
