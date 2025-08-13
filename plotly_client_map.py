import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import requests
import time
import json
import os
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
import hashlib
import numpy as np
from sklearn.cluster import DBSCAN
from collections import Counter

# Configuration de la page
st.set_page_config(
    page_title="Carte Interactive des Clients",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS personnalisé
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
        text-align: center;
        margin-bottom: 2rem;
    }
    .metric-card {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 10px;
        border-left: 4px solid #1f77b4;
    }
</style>
""", unsafe_allow_html=True)

# Classe pour la gestion du cache géocodage
class GeocodeCache:
    def __init__(self, cache_file='geocode_cache.json'):
        self.cache_file = cache_file
        self.cache = self.load_cache()
        # Geolocator plus agressif pour la vitesse
        self.geolocator = Nominatim(
            user_agent="client_map_app_v2",
            timeout=8  # Timeout global réduit
        )
    
    def load_cache(self):
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def save_cache(self):
        # Sauvegarder le cache tous les 10 géocodages pour éviter les I/O trop fréquents
        if not hasattr(self, '_save_counter'):
            self._save_counter = 0
        self._save_counter += 1
        
        if self._save_counter % 10 == 0 or len(self.cache) < 10:  # Forcer la sauvegarde si peu de données
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
    
    def geocode_address(self, address, code_postal=None):
        if not address or pd.isna(address):
            return None, None
            
        address = str(address).strip()
        
        # Construire l'adresse avec le code postal si disponible
        if code_postal and not pd.isna(code_postal):
            code_postal_str = str(code_postal).strip()
            # Nettoyer le code postal (garder seulement les chiffres)
            code_postal_clean = ''.join(filter(str.isdigit, code_postal_str))
            if len(code_postal_clean) >= 4:  # Code postal français valide
                full_address = f"{address}, {code_postal_clean}, France"
            else:
                full_address = f"{address}, France"
        else:
            full_address = f"{address}, France"
        
        cache_key = hashlib.md5(full_address.lower().encode()).hexdigest()
        
        if cache_key in self.cache:
            coords = self.cache[cache_key]
            if coords:
                return coords['lat'], coords['lng']
            return None, None
        
        try:
            time.sleep(0.02)  # Réduit encore : 0.02 secondes (risqué mais plus rapide)
            location = self.geolocator.geocode(full_address, timeout=8)  # Timeout réduit à 8s
            if location:
                coords = {'lat': location.latitude, 'lng': location.longitude}
                self.cache[cache_key] = coords
                self.save_cache()
                return location.latitude, location.longitude
            else:
                # Si échec avec code postal, essayer sans (sans délai supplémentaire)
                if code_postal:
                    fallback_address = f"{address}, France"
                    location = self.geolocator.geocode(fallback_address, timeout=8)
                    if location:
                        coords = {'lat': location.latitude, 'lng': location.longitude}
                        self.cache[cache_key] = coords
                        self.save_cache()
                        return location.latitude, location.longitude
                
                self.cache[cache_key] = None
                self.save_cache()
                return None, None
        except Exception as e:
            # En cas d'erreur de rate limit, attendre un peu plus et réessayer une fois
            if "rate limit" in str(e).lower() or "too many requests" in str(e).lower():
                time.sleep(1)
                try:
                    location = self.geolocator.geocode(full_address, timeout=8)
                    if location:
                        coords = {'lat': location.latitude, 'lng': location.longitude}
                        self.cache[cache_key] = coords
                        self.save_cache()
                        return location.latitude, location.longitude
                except:
                    pass
            
            # Mise en cache de l'échec pour éviter de réessayer
            self.cache[cache_key] = None
            self.save_cache()
            return None, None

# Initialisation du cache géocodage
@st.cache_resource
def get_geocode_cache():
    return GeocodeCache()

# Fonction pour vider le cache
def clear_cache():
    """Vide tous les caches de l'application"""
    st.cache_data.clear()
    st.cache_resource.clear()

# Fonction pour traiter les données Excel
@st.cache_data
def process_excel_data(file):
    try:
        df = pd.read_excel(file, engine='openpyxl')
        df.columns = df.columns.str.strip()
        
        st.write("Colonnes détectées:", list(df.columns))
        
        column_mapping = {}
        for col in df.columns:
            col_lower = col.lower()
            if any(word in col_lower for word in ['nom', 'client', 'entreprise', 'société', 'code_dossier', 'code_du_dossier']):
                column_mapping['nom_client'] = col
            elif any(word in col_lower for word in ['ville', 'city']):
                column_mapping['ville'] = col
            elif any(word in col_lower for word in ['code_postal', 'cp', 'postal', 'zip']):
                column_mapping['code_postal'] = col
            elif any(word in col_lower for word in ['adresse', 'address']):
                column_mapping['adresse'] = col
            elif any(word in col_lower for word in ['responsable', 'manager']):
                column_mapping['responsable'] = col
            elif any(word in col_lower for word in ['collaborateur', 'commercial']):
                column_mapping['collaborateur'] = col
            elif any(word in col_lower for word in ['activité', 'secteur', 'activity']):
                column_mapping['activite'] = col
            elif any(word in col_lower for word in ['forme_juri', 'forme', 'juridique', 'type']):
                column_mapping['forme'] = col
            elif any(word in col_lower for word in ['site']):
                column_mapping['site'] = col
        
        return df, column_mapping
    
    except Exception as e:
        st.error(f"Erreur lors de la lecture du fichier: {e}")
        return None, None

def create_plotly_map(df, column_mapping, geocache, filters):
    # Application des filtres
    filtered_df = df.copy()
    
    for filter_key, filter_values in filters.items():
        if filter_values and filter_key in column_mapping:
            col_name = column_mapping[filter_key]
            if col_name in filtered_df.columns:
                filtered_df = filtered_df[filtered_df[col_name].isin(filter_values)]
    
    if filtered_df.empty:
        st.warning("Aucun client ne correspond aux filtres sélectionnés.")
        return None
    
    # Géocodage des villes
    if 'ville' in column_mapping:
        ville_col = column_mapping['ville']
        villes_uniques = filtered_df[ville_col].dropna().unique()
    else:
        st.error("Aucune colonne 'ville' détectée dans les données.")
        return None
    
    # Utilisation de la méthode de géocodage similaire au code joint
    progress_bar = st.progress(0)
    client_locations = {}
    ville_clients = {}
    
    # Compter le nombre de clients par ville
    ville_client_count = {}
    for _, client in filtered_df.iterrows():
        ville = client[ville_col]
        ville_client_count[ville] = ville_client_count.get(ville, 0) + 1
    
    # Stocker les clients par ville pour affichage détaillé
    for _, client in filtered_df.iterrows():
        ville = client[ville_col]
        if ville not in ville_clients:
            ville_clients[ville] = []
        
        # Utiliser différentes colonnes possibles pour le nom du client
        nom_client = 'Client inconnu'
        if 'nom_client' in column_mapping:
            nom_client = client.get(column_mapping['nom_client'], 'Client inconnu')
        
        ville_clients[ville].append({
            'nom': nom_client,
            'siret': client.get('siret', ''),
            'code_naf': client.get('code_naf', ''),
            'forme_juri': client.get('forme_juri', ''),
            'responsable': client.get(column_mapping.get('responsable', ''), ''),
            'collaborateur': client.get(column_mapping.get('collaborateur', ''), ''),
            'activite': client.get(column_mapping.get('activite', ''), ''),
            'forme': client.get(column_mapping.get('forme', ''), ''),
            'site': client.get(column_mapping.get('site', ''), '')
        })
    
    # Géocodage des villes uniques
    map_data = []
    processed_cities = 0
    
    # Géocodage des villes uniques avec codes postaux
    map_data = []
    processed_cities = 0
    
    # Créer des combinaisons ville + code postal uniques
    ville_cp_combinations = set()
    if 'code_postal' in column_mapping:
        cp_col = column_mapping['code_postal']
        for _, client in filtered_df.iterrows():
            ville = client[ville_col]
            cp = client.get(cp_col, None)
            if pd.notna(ville):
                ville_cp_combinations.add((ville, cp))
    else:
        for ville in villes_uniques:
            ville_cp_combinations.add((ville, None))
    
    # Compter les clients par combinaison ville+CP
    ville_cp_client_count = {}
    ville_cp_clients = {}
    
    for _, client in filtered_df.iterrows():
        ville = client[ville_col]
        cp = client.get(column_mapping.get('code_postal', ''), None) if 'code_postal' in column_mapping else None
        ville_cp_key = (ville, cp)
        
        ville_cp_client_count[ville_cp_key] = ville_cp_client_count.get(ville_cp_key, 0) + 1
        
        if ville_cp_key not in ville_cp_clients:
            ville_cp_clients[ville_cp_key] = []
        
        # Utiliser différentes colonnes possibles pour le nom du client
        nom_client = 'Client inconnu'
        if 'nom_client' in column_mapping:
            nom_client = client.get(column_mapping['nom_client'], 'Client inconnu')
        
        ville_cp_clients[ville_cp_key].append({
            'nom': nom_client,
            'siret': client.get('siret', ''),
            'code_naf': client.get('code_naf', ''),
            'forme_juri': client.get('forme_juri', ''),
            'responsable': client.get(column_mapping.get('responsable', ''), ''),
            'collaborateur': client.get(column_mapping.get('collaborateur', ''), ''),
            'activite': client.get(column_mapping.get('activite', ''), ''),
            'forme': client.get(column_mapping.get('forme', ''), ''),
            'site': client.get(column_mapping.get('site', ''), '')
        })
    
    # Géocodage avec codes postaux
    for ville_cp in ville_cp_combinations:
        ville, cp = ville_cp
        processed_cities += 1
        progress = processed_cities / len(ville_cp_combinations)
        progress_bar.progress(progress)
        
        # Utiliser la nouvelle méthode de géocodage avec code postal
        lat, lon = geocache.geocode_address(ville, cp)
        if not (lat and lon):
            continue
        
        # Déterminer la taille du marqueur
        nb_clients = ville_cp_client_count.get(ville_cp, 0)
        radius = min(50, max(8, nb_clients * 3))
        
        # Créer le texte de l'info-bulle avec code postal
        ville_display = f"{ville}" + (f" ({cp})" if cp and pd.notna(cp) else "")
        popup_text = f"<b>{ville_display}</b><br>Nombre de clients: {nb_clients}<br><br>"
        
        clients_ville_cp = ville_cp_clients.get(ville_cp, [])
        for i, client in enumerate(clients_ville_cp[:10]):
            popup_text += f"• {client['nom']}"
            if client['responsable']:
                popup_text += f" (Resp: {client['responsable']})"
            popup_text += "<br>"
        
        if len(clients_ville_cp) > 10:
            popup_text += f"... et {len(clients_ville_cp) - 10} autres clients"
        
        map_data.append({
            'ville': ville,
            'code_postal': cp if pd.notna(cp) else '',
            'ville_display': ville_display,
            'lat': lat,
            'lon': lon,
            'nb_clients': nb_clients,
            'hover_text': popup_text,
            'size': radius,
            'clients': clients_ville_cp
        })
    
    progress_bar.empty()
    
    if not map_data:
        st.error("Aucune ville n'a pu être géocodée.")
        return None
    
    # Création du DataFrame pour Plotly
    map_df = pd.DataFrame(map_data)
    
    # Création de la carte avec Plotly
    fig = go.Figure()
    
    fig.add_trace(go.Scattermapbox(
        lat=map_df['lat'],
        lon=map_df['lon'],
        mode='markers',
        marker=dict(
            size=map_df['size'],
            color='#3282b8',
            opacity=0.7
        ),
        text=map_df['hover_text'],
        hovertemplate='%{text}<extra></extra>',
        name='Clients'
    ))
    
    # Configuration de la carte
    if not map_df.empty:
        center_lat = map_df['lat'].mean()
        center_lon = map_df['lon'].mean()
    else:
        center_lat, center_lon = 46.603354, 1.888334
    
    fig.update_layout(
        mapbox=dict(
            accesstoken=None,
            style="open-street-map",
            center=dict(lat=center_lat, lon=center_lon),
            zoom=6
        ),
        height=600,
        margin=dict(t=0, b=0, l=0, r=0),
        showlegend=False,
        title=dict(
            text="Carte Interactive des Clients",
            x=0.5,
            font=dict(size=16, color="#1f77b4")
        ),
        # Configuration pour permettre l'interaction
        dragmode='pan'
    )
    
    return fig, map_df, len(filtered_df)

def analyze_city_distribution(df, column_mapping, geocache):
    """Analyse la distribution des clients par ville avec gradient de couleur"""
    
    if 'ville' not in column_mapping:
        return None
    
    ville_col = column_mapping['ville']
    cp_col = column_mapping.get('code_postal', None)
    villes_data = []
    
    # Collecter les données avec ville + code postal
    if cp_col:
        # Grouper par ville + code postal
        ville_cp_counts = df.groupby([ville_col, cp_col]).size().reset_index(name='count')
        
        for _, row in ville_cp_counts.iterrows():
            ville = row[ville_col]
            cp = row[cp_col]
            count = row['count']
            
            if pd.notna(ville):
                lat, lon = geocache.geocode_address(ville, cp)
                if lat and lon:
                    ville_display = f"{ville}" + (f" ({cp})" if pd.notna(cp) else "")
                    villes_data.append({
                        'ville': ville,
                        'code_postal': cp if pd.notna(cp) else '',
                        'ville_display': ville_display,
                        'lat': lat,
                        'lon': lon,
                        'nb_clients': count
                    })
    else:
        # Fallback : grouper seulement par ville
        ville_counts = df[ville_col].value_counts()
        
        for ville, count in ville_counts.items():
            if pd.notna(ville):
                lat, lon = geocache.geocode_address(ville)
                if lat and lon:
                    villes_data.append({
                        'ville': ville,
                        'code_postal': '',
                        'ville_display': ville,
                        'lat': lat,
                        'lon': lon,
                        'nb_clients': count
                    })
    
    if not villes_data:
        return None
    
    villes_df = pd.DataFrame(villes_data)
    
    # Définir les catégories de concentration
    q25 = villes_df['nb_clients'].quantile(0.25)
    q50 = villes_df['nb_clients'].quantile(0.50)
    q75 = villes_df['nb_clients'].quantile(0.75)
    q90 = villes_df['nb_clients'].quantile(0.90)
    
    def categorize_concentration(nb_clients):
        if nb_clients >= q90:
            return "Très Forte (>90e percentile)"
        elif nb_clients >= q75:
            return "Forte (75-90e percentile)"
        elif nb_clients >= q50:
            return "Moyenne (50-75e percentile)"
        elif nb_clients >= q25:
            return "Faible (25-50e percentile)"
        else:
            return "Très Faible (<25e percentile)"
    
    villes_df['categorie'] = villes_df['nb_clients'].apply(categorize_concentration)
    
    # Analyse des villes
    cities_analysis = {
        'tres_forte': [],
        'forte': [],
        'moyenne': [],
        'faible': [],
        'tres_faible': [],
        'statistiques': {}
    }
    
    # Statistiques globales
    total_clients = villes_df['nb_clients'].sum()
    moyenne_clients = villes_df['nb_clients'].mean()
    mediane_clients = villes_df['nb_clients'].median()
    max_clients = villes_df['nb_clients'].max()
    min_clients = villes_df['nb_clients'].min()
    
    cities_analysis['statistiques'] = {
        'total_clients': total_clients,
        'total_villes': len(villes_df),
        'moyenne_clients_par_ville': round(moyenne_clients, 2),
        'mediane_clients_par_ville': round(mediane_clients, 2),
        'max_clients': max_clients,
        'min_clients': min_clients,
        'seuil_q25': round(q25, 1),
        'seuil_q50': round(q50, 1),
        'seuil_q75': round(q75, 1),
        'seuil_q90': round(q90, 1)
    }
    
    # Répartir les villes par catégorie
    for _, ville in villes_df.iterrows():
        ville_info = {
            'ville': ville['ville_display'],  # Afficher ville + CP
            'nb_clients': ville['nb_clients'],
            'lat': ville['lat'],
            'lon': ville['lon'],
            'pourcentage_total': round((ville['nb_clients'] / total_clients) * 100, 2)
        }
        
        if ville['categorie'] == "Très Forte (>90e percentile)":
            cities_analysis['tres_forte'].append(ville_info)
        elif ville['categorie'] == "Forte (75-90e percentile)":
            cities_analysis['forte'].append(ville_info)
        elif ville['categorie'] == "Moyenne (50-75e percentile)":
            cities_analysis['moyenne'].append(ville_info)
        elif ville['categorie'] == "Faible (25-50e percentile)":
            cities_analysis['faible'].append(ville_info)
        else:
            cities_analysis['tres_faible'].append(ville_info)
    
    # Trier chaque catégorie par nombre de clients décroissant
    for key in ['tres_forte', 'forte', 'moyenne', 'faible', 'tres_faible']:
        cities_analysis[key] = sorted(cities_analysis[key], key=lambda x: x['nb_clients'], reverse=True)
    
    return cities_analysis, villes_df

def create_concentration_map(villes_df, cities_analysis, zoom_region=None):
    """Crée une carte avec gradient de couleur selon la concentration de clients"""
    
    fig = go.Figure()
    
    # Définir les couleurs pour chaque catégorie
    color_map = {
        "Très Forte (>90e percentile)": '#8B0000',      # Rouge très foncé
        "Forte (75-90e percentile)": '#FF0000',          # Rouge
        "Moyenne (50-75e percentile)": '#FF8C00',        # Orange
        "Faible (25-50e percentile)": '#FFD700',         # Jaune/Or
        "Très Faible (<25e percentile)": '#90EE90'       # Vert clair
    }
    
    # Ajouter les traces pour chaque catégorie
    for categorie, color in color_map.items():
        villes_cat = villes_df[villes_df['categorie'] == categorie]
        
        if not villes_cat.empty:
            fig.add_trace(go.Scattermapbox(
                lat=villes_cat['lat'],
                lon=villes_cat['lon'],
                mode='markers',
                marker=dict(
                    size=np.clip(villes_cat['nb_clients'] * 0.8 + 10, 10, 30),  # Taille limitée entre 10 et 30 pixels
                    color=color,
                    opacity=0.8
                ),
                text=[f"<b>{row['ville']}</b><br>{categorie}<br>{row['nb_clients']} clients<br>{round((row['nb_clients']/villes_df['nb_clients'].sum())*100, 1)}% du total" 
                      for _, row in villes_cat.iterrows()],
                hovertemplate='%{text}<extra></extra>',
                name=categorie,
                showlegend=True
            ))
    
    # Configuration de la carte avec zoom conditionnel
    center_lat = villes_df['lat'].mean()
    center_lon = villes_df['lon'].mean()
    zoom_level = 6
    
    # Définir les coordonnées et zoom pour différentes régions
    zoom_configs = {
        "idf": {"lat": 48.8566, "lon": 2.3522, "zoom": 9},  # Île-de-France
        "paca": {"lat": 43.9352, "lon": 6.0679, "zoom": 8},  # PACA
        "nouvelle_aquitaine": {"lat": 45.8336, "lon": 0.5683, "zoom": 7},  # Nouvelle-Aquitaine
        "auvergne_rhone_alpes": {"lat": 45.7640, "lon": 4.8357, "zoom": 7},  # Auvergne-Rhône-Alpes
        "france": {"lat": center_lat, "lon": center_lon, "zoom": 6}  # Vue d'ensemble
    }
    
    if zoom_region and zoom_region in zoom_configs:
        config = zoom_configs[zoom_region]
        center_lat = config["lat"]
        center_lon = config["lon"]
        zoom_level = config["zoom"]
    
    fig.update_layout(
        mapbox=dict(
            accesstoken=None,
            style="open-street-map",
            center=dict(lat=center_lat, lon=center_lon),
            zoom=zoom_level
        ),
        height=700,
        margin=dict(t=40, b=0, l=0, r=0),
        title=dict(
            text="Concentration de Clients par Ville - Zoom interactif disponible",
            x=0.5,
            font=dict(size=18, color="#1f77b4")
        ),
        legend=dict(
            yanchor="top",
            y=0.99,
            xanchor="left",
            x=0.01,
            bgcolor="rgba(255,255,255,0.9)",
            bordercolor="rgba(0,0,0,0.2)",
            borderwidth=1
        ),
        # Configuration pour permettre l'interaction et le zoom
        dragmode='pan'
    )
    
    return fig

def show_city_clients(ville_nom, df, column_mapping, filters):
    """Affiche les clients d'une ville triés par ordre alphabétique"""
    
    # Appliquer les mêmes filtres que sur la carte
    filtered_df = df.copy()
    for filter_key, filter_values in filters.items():
        if filter_values and filter_key in column_mapping:
            col_name = column_mapping[filter_key]
            if col_name in filtered_df.columns:
                filtered_df = filtered_df[filtered_df[col_name].isin(filter_values)]
    
    ville_col = column_mapping['ville']
    clients_ville = filtered_df[filtered_df[ville_col] == ville_nom].copy()
    
    if clients_ville.empty:
        st.warning(f"Aucun client trouvé pour {ville_nom}")
        return
    
    # Trier les clients par nom
    nom_col = column_mapping.get('nom_client', 'nom')
    if nom_col in clients_ville.columns:
        clients_ville = clients_ville.sort_values(nom_col)
    
    st.markdown(f"### 👥 Clients de {ville_nom} ({len(clients_ville)} clients)")
    
    # Créer un tableau avec les informations des clients
    display_data = []
    
    for _, client in clients_ville.iterrows():
        # Utiliser différentes colonnes possibles pour le nom du client
        nom_client = 'N/A'
        if 'nom_client' in column_mapping:
            nom_client = client.get(column_mapping['nom_client'], 'N/A')
        
        row_data = {
            'Nom': nom_client,
            'SIRET': client.get('siret', 'N/A'),
            'Code NAF': client.get('code_naf', 'N/A'),
            'Forme Juridique': client.get('forme_juri', 'N/A')
        }
        
        # Ajouter les colonnes supplémentaires si elles existent
        if 'responsable' in column_mapping and column_mapping['responsable'] in client.index:
            row_data['Responsable'] = client.get(column_mapping['responsable'], 'N/A')
        
        if 'collaborateur' in column_mapping and column_mapping['collaborateur'] in client.index:
            row_data['Collaborateur'] = client.get(column_mapping['collaborateur'], 'N/A')
        
        if 'activite' in column_mapping and column_mapping['activite'] in client.index:
            row_data['Secteur d\'activité'] = client.get(column_mapping['activite'], 'N/A')
        
        if 'forme' in column_mapping and column_mapping['forme'] in client.index:
            row_data['Forme'] = client.get(column_mapping['forme'], 'N/A')
        
        if 'site' in column_mapping and column_mapping['site'] in client.index:
            row_data['Site'] = client.get(column_mapping['site'], 'N/A')
        
        display_data.append(row_data)
    
    # Afficher le tableau
    if display_data:
        clients_df = pd.DataFrame(display_data)
        st.dataframe(clients_df, use_container_width=True)
        
        # Bouton d'export pour cette ville
        if st.button(f"Exporter les clients de {ville_nom} en CSV", key=f"export_{ville_nom}"):
            csv = clients_df.to_csv(index=False, sep=';')
            st.download_button(
                label="Télécharger le fichier CSV",
                data=csv,
                file_name=f"clients_{ville_nom}.csv",
                mime="text/csv",
                key=f"download_{ville_nom}"
            )
    else:
        st.warning("Aucune donnée à afficher pour cette ville.")

def main():
    st.markdown('<h1 class="main-header">🗺️ Carte Interactive des Clients</h1>', unsafe_allow_html=True)
    
    # Zone de téléchargement avec bouton d'actualisation
    col1, col2 = st.columns([3, 1])
    
    with col1:
        st.subheader("📁 Téléchargement des données")
        uploaded_file = st.file_uploader(
            "Choisissez votre fichier Excel contenant les données clients",
            type=['xlsx', 'xls']
        )
    
    with col2:
        st.subheader("🔄 Actualisation")
        if st.button("🔄 Vider le cache et actualiser", 
                    help="Cliquez ici si vous avez modifié votre fichier Excel",
                    type="primary"):
            clear_cache()
            st.success("✅ Cache vidé ! Re-téléchargez votre fichier pour voir les modifications.")
            st.rerun()
    
    if uploaded_file is not None:
        with st.spinner("Traitement du fichier Excel..."):
            df, column_mapping = process_excel_data(uploaded_file)
        
        if df is not None:
            st.success(f"Fichier traité avec succès ! {len(df)} enregistrements trouvés.")
            
            # Afficher le mapping des colonnes détectées
            if column_mapping:
                st.info("🔍 **Colonnes détectées automatiquement :**")
                col_info = []
                for key, value in column_mapping.items():
                    if key == 'nom_client':
                        col_info.append(f"• **Nom client** : {value}")
                    elif key == 'ville':
                        col_info.append(f"• **Ville** : {value}")
                    elif key == 'code_postal':
                        col_info.append(f"• **Code postal** : {value}")
                    elif key == 'responsable':
                        col_info.append(f"• **Responsable** : {value}")
                    elif key == 'collaborateur':
                        col_info.append(f"• **Collaborateur** : {value}")
                    elif key == 'activite':
                        col_info.append(f"• **Activité** : {value}")
                    elif key == 'forme':
                        col_info.append(f"• **Forme juridique** : {value}")
                    elif key == 'site':
                        col_info.append(f"• **Site** : {value}")
                
                if col_info:
                    st.markdown("<br>".join(col_info), unsafe_allow_html=True)
                else:
                    st.warning("⚠️ Aucune colonne standard détectée automatiquement")
            
            # Métriques
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.metric("Total Clients", len(df))
                st.markdown('</div>', unsafe_allow_html=True)
            
            with col2:
                if 'ville' in column_mapping:
                    villes_uniques = df[column_mapping['ville']].nunique()
                    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                    st.metric("Villes", villes_uniques)
                    st.markdown('</div>', unsafe_allow_html=True)
            
            with col3:
                if 'responsable' in column_mapping:
                    responsables_uniques = df[column_mapping['responsable']].nunique()
                    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                    st.metric("Responsables", responsables_uniques)
                    st.markdown('</div>', unsafe_allow_html=True)
            
            with col4:
                if 'activite' in column_mapping:
                    activites_uniques = df[column_mapping['activite']].nunique()
                    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                    st.metric("Secteurs", activites_uniques)
                    st.markdown('</div>', unsafe_allow_html=True)
            
            # Filtres dans la sidebar
            st.sidebar.subheader("🔍 Filtres")
            
            filters = {}
            
            # Filtre par Responsable
            if 'responsable' in column_mapping:
                responsable_col = column_mapping['responsable']
                if responsable_col in df.columns:
                    responsables = sorted(df[responsable_col].dropna().unique())
                    filters['responsable'] = st.sidebar.multiselect("Responsable", responsables)
            
            # Filtre par Collaborateur
            if 'collaborateur' in column_mapping:
                collaborateur_col = column_mapping['collaborateur']
                if collaborateur_col in df.columns:
                    collaborateurs = sorted(df[collaborateur_col].dropna().unique())
                    filters['collaborateur'] = st.sidebar.multiselect("Collaborateur", collaborateurs)
            
            # Filtre par Activité
            if 'activite' in column_mapping:
                activite_col = column_mapping['activite']
                if activite_col in df.columns:
                    activites = sorted(df[activite_col].dropna().unique())
                    filters['activite'] = st.sidebar.multiselect("Secteur d'activité", activites)
            
            # Filtre par Forme
            if 'forme' in column_mapping:
                forme_col = column_mapping['forme']
                if forme_col in df.columns:
                    formes = sorted(df[forme_col].dropna().unique())
                    filters['forme'] = st.sidebar.multiselect("Forme juridique", formes)
            
            # Filtre par Site
            if 'site' in column_mapping:
                site_col = column_mapping['site']
                if site_col in df.columns:
                    sites = sorted(df[site_col].dropna().unique())
                    filters['site'] = st.sidebar.multiselect("Site", sites)
            
            if st.sidebar.button("🔄 Réinitialiser les filtres"):
                st.rerun()
            
            # Séparateur et section actualisation dans la sidebar
            st.sidebar.markdown("---")
            st.sidebar.subheader("⚡ Actualisation")
            
            if st.sidebar.button("🔄 Actualiser les données", 
                                help="Videz le cache et rechargez les données"):
                clear_cache()
                st.sidebar.success("Cache vidé !")
                st.rerun()
            
            st.sidebar.markdown("💡 **Astuce :** Cliquez sur ce bouton si vous avez modifié votre fichier Excel")
            
            # Création de la carte
            st.subheader("🗺️ Carte des clients")
            
            geocache = get_geocode_cache()
            
            with st.spinner("Création de la carte interactive..."):
                result = create_plotly_map(df, column_mapping, geocache, filters)
            
            if result:
                fig, map_df, total_clients_carte = result
                
                # Afficher le nombre total de clients sur la carte
                st.info(f"📊 **{total_clients_carte} clients** sont affichés sur cette carte")
                
                # Affichage de la carte avec configuration interactive
                st.plotly_chart(
                    fig, 
                    use_container_width=True,
                    config={
                        'displayModeBar': True,
                        'displaylogo': False,
                        'modeBarButtonsToAdd': ['pan2d', 'zoomIn2d', 'zoomOut2d', 'autoScale2d', 'resetScale2d'],
                        'modeBarButtonsToRemove': ['lasso2d', 'select2d'],
                        'scrollZoom': True,
                        'doubleClick': 'reset+autosize',
                        'toImageButtonOptions': {
                            'format': 'png',
                            'filename': 'carte_clients',
                            'height': 600,
                            'width': 800,
                            'scale': 1
                        }
                    }
                )
                
                # Section pour sélectionner une ville
                st.subheader("🏙️ Sélection de ville")
                
                if not map_df.empty:
                    villes_options = []
                    for _, row in map_df.sort_values('nb_clients', ascending=False).iterrows():
                        ville_display = row.get('ville_display', row['ville'])
                        villes_options.append(f"{ville_display} ({row['nb_clients']} clients)")
                    
                    ville_selectionnee = st.selectbox(
                        "Choisissez une ville pour voir ses clients :",
                        ["Sélectionnez une ville..."] + villes_options
                    )
                    
                    if ville_selectionnee != "Sélectionnez une ville...":
                        # Extraire le nom de la ville (avant la parenthèse des clients)
                        ville_display = ville_selectionnee.split(' (')[0]
                        # Trouver la ville correspondante dans le DataFrame
                        matching_row = map_df[map_df.get('ville_display', map_df['ville']) == ville_display]
                        if not matching_row.empty:
                            ville_nom = matching_row.iloc[0]['ville']
                            show_city_clients(ville_nom, df, column_mapping, filters)
                
                # Tableau récapitulatif avec codes postaux
                st.subheader("📊 Récapitulatif par ville")
                if 'code_postal' in map_df.columns:
                    summary_df = map_df[['ville_display', 'nb_clients']].sort_values('nb_clients', ascending=False)
                    summary_df.columns = ['Ville (Code Postal)', 'Nombre de clients']
                else:
                    summary_df = map_df[['ville', 'nb_clients']].sort_values('nb_clients', ascending=False)
                    summary_df.columns = ['Ville', 'Nombre de clients']
                st.dataframe(summary_df, use_container_width=True)
                
                # Instructions
                st.markdown("""
                ### 📋 Instructions d'utilisation
                
                - **🖱️ Navigation** : 
                  - **Zoom** : Utilisez la molette de la souris ou les boutons +/- dans la barre d'outils
                  - **Déplacement** : Cliquez et glissez pour déplacer la carte
                  - **Reset** : Double-cliquez pour revenir à la vue initiale
                - **🔧 Barre d'outils** : Utilisez les icônes en haut à droite de la carte
                  - 📷 Télécharger l'image de la carte
                  - 🔍 Zoom avant/arrière
                  - 🏠 Revenir à la vue d'ensemble
                - **🎛️ Filtres** : Utilisez les filtres dans la barre latérale pour affiner l'affichage
                - **🔍 Marqueurs** : Survolez un marqueur pour voir les informations de la ville
                - **📋 Sélection** : Utilisez le menu déroulant pour voir le détail des clients par ville
                - **💾 Export** : Exportez les données d'une ville spécifique en CSV
                - **🔄 Actualisation** : Si vous modifiez votre fichier Excel, utilisez le bouton "Actualiser les données"
                
                ### 🔄 Mise à jour des données
                
                **Si vous ajoutez/modifiez des clients dans votre fichier Excel :**
                1. **Sauvegardez** votre fichier Excel
                2. **Cliquez** sur "🔄 Actualiser les données" (en haut à droite ou dans la sidebar)
                3. **Re-téléchargez** votre fichier mis à jour
                4. **La carte se met à jour** automatiquement avec les nouvelles données
                
                ### 📱 Optimisé mobile
                Cette carte est optimisée pour fonctionner sur tous les appareils.
                """)
                
                # NOUVELLE SECTION : ANALYSE DE CONCENTRATION PAR VILLE
                st.markdown("---")
                st.header("📊 Analyse de Concentration par Ville")
                
                if st.button("🔍 Lancer l'analyse de concentration", type="primary"):
                    with st.spinner("Analyse en cours..."):
                        analysis_result = analyze_city_distribution(df, column_mapping, geocache)
                    
                    if analysis_result:
                        cities_analysis, villes_df = analysis_result
                        
                        # Affichage des statistiques globales
                        st.subheader("📈 Statistiques Globales")
                        
                        col1, col2, col3, col4, col5 = st.columns(5)
                        with col1:
                            st.metric("Total Clients", cities_analysis['statistiques']['total_clients'])
                        with col2:
                            st.metric("Total Villes", cities_analysis['statistiques']['total_villes'])
                        with col3:
                            st.metric("Moyenne/Ville", cities_analysis['statistiques']['moyenne_clients_par_ville'])
                        with col4:
                            st.metric("Maximum", cities_analysis['statistiques']['max_clients'])
                        with col5:
                            st.metric("Minimum", cities_analysis['statistiques']['min_clients'])
                        
                        # Affichage des seuils
                        st.info(f"""
                        📊 **Seuils de concentration :**
                        • Très Forte : ≥ {cities_analysis['statistiques']['seuil_q90']} clients (>90e percentile)
                        • Forte : {cities_analysis['statistiques']['seuil_q75']} - {cities_analysis['statistiques']['seuil_q90']} clients (75-90e percentile)
                        • Moyenne : {cities_analysis['statistiques']['seuil_q50']} - {cities_analysis['statistiques']['seuil_q75']} clients (50-75e percentile)
                        • Faible : {cities_analysis['statistiques']['seuil_q25']} - {cities_analysis['statistiques']['seuil_q50']} clients (25-50e percentile)
                        • Très Faible : < {cities_analysis['statistiques']['seuil_q25']} clients (<25e percentile)
                        """)
                        
                        # Carte de concentration avec contrôles de zoom avancés
                        st.subheader("🗺️ Carte de Concentration par Ville")
                        
                        # Créer la carte sans zoom régional
                        concentration_map = create_concentration_map(villes_df, cities_analysis)
                        
                        st.plotly_chart(
                            concentration_map, 
                            use_container_width=True,
                            config={
                                'displayModeBar': True,
                                'displaylogo': False,
                                'modeBarButtonsToAdd': ['pan2d', 'zoomIn2d', 'zoomOut2d', 'autoScale2d', 'resetScale2d'],
                                'modeBarButtonsToRemove': ['lasso2d', 'select2d'],
                                'scrollZoom': True,
                                'doubleClick': 'reset+autosize',
                                'toImageButtonOptions': {
                                    'format': 'png',
                                    'filename': 'carte_concentration_clients',
                                    'height': 700,
                                    'width': 1000,
                                    'scale': 2
                                }
                            }
                        )
                        
                        # Légende simplifiée sans les boutons de zoom
                        st.markdown("""
                        **🎨 Légende de la carte :**
                        - 🟫 **Très Forte** : Concentration maximale (>90e percentile)
                        - 🔴 **Forte** : Forte concentration (75-90e percentile)
                        - 🟠 **Moyenne** : Concentration intermédiaire (50-75e percentile)
                        - 🟡 **Faible** : Faible concentration (25-50e percentile)
                        - 🟢 **Très Faible** : Concentration minimale (<25e percentile)
                        
                        **🔧 Contrôles interactifs :**
                        - **🖱️ Zoom manuel** : Molette de souris ou boutons +/- dans la barre d'outils
                        - **👆 Déplacement** : Cliquer-glisser pour naviguer sur la carte
                        - **🏠 Reset** : Double-clic pour revenir à la vue d'ensemble
                        - **📷 Export HD** : Bouton caméra pour télécharger en haute qualité
                        - **🔍 Détails** : Survoler les marqueurs pour voir les informations détaillées
                        
                        *La taille des marqueurs est proportionnelle au nombre de clients (10-30 pixels).*
                        """)
                        
                        # Analyses détaillées par catégorie
                        tab1, tab2, tab3, tab4, tab5 = st.tabs(["🟫 Très Forte", "🔴 Forte", "🟠 Moyenne", "🟡 Faible", "🟢 Très Faible"])
                        
                        with tab1:
                            st.subheader("🟫 Villes à Très Forte Concentration")
                            if cities_analysis['tres_forte']:
                                tres_forte_df = pd.DataFrame([{
                                    'Ville': v['ville'],
                                    'Nb Clients': v['nb_clients'],
                                    '% du Total': f"{v['pourcentage_total']}%"
                                } for v in cities_analysis['tres_forte']])
                                
                                st.dataframe(tres_forte_df, use_container_width=True)
                                
                                # Graphique en barres
                                fig_bar = px.bar(
                                    tres_forte_df, 
                                    x='Ville', 
                                    y='Nb Clients',
                                    title="Répartition des clients - Villes à très forte concentration",
                                    color_discrete_sequence=['#8B0000']
                                )
                                fig_bar.update_layout(xaxis_tickangle=-45)
                                st.plotly_chart(fig_bar, use_container_width=True)
                                
                                st.markdown("""
                                **💡 Recommandations :**
                                - Ces villes représentent vos **marchés leaders**
                                - **Fidélisation** prioritaire des clients existants
                                - **Services premium** et support renforcé
                                - **Analyse concurrentielle** approfondie pour maintenir la position
                                - **Expansion** vers les zones géographiques proches
                                """)
                            else:
                                st.info("Aucune ville à très forte concentration identifiée.")
                        
                        with tab2:
                            st.subheader("🔴 Villes à Forte Concentration")
                            if cities_analysis['forte']:
                                forte_df = pd.DataFrame([{
                                    'Ville': v['ville'],
                                    'Nb Clients': v['nb_clients'],
                                    '% du Total': f"{v['pourcentage_total']}%"
                                } for v in cities_analysis['forte']])
                                
                                st.dataframe(forte_df, use_container_width=True)
                                
                                # Graphique en barres
                                fig_bar = px.bar(
                                    forte_df, 
                                    x='Ville', 
                                    y='Nb Clients',
                                    title="Répartition des clients - Villes à forte concentration",
                                    color_discrete_sequence=['#FF0000']
                                )
                                fig_bar.update_layout(xaxis_tickangle=-45)
                                st.plotly_chart(fig_bar, use_container_width=True)
                                
                                st.markdown("""
                                **💡 Recommandations :**
                                - Villes avec **fort potentiel** de croissance
                                - **Investissement** en ressources commerciales
                                - **Campagnes marketing** ciblées
                                - **Partenariats** avec des acteurs locaux
                                - **Monitoring** de la satisfaction client
                                """)
                            else:
                                st.info("Aucune ville à forte concentration identifiée.")
                        
                        with tab3:
                            st.subheader("🟠 Villes à Concentration Moyenne")
                            if cities_analysis['moyenne']:
                                moyenne_df = pd.DataFrame([{
                                    'Ville': v['ville'],
                                    'Nb Clients': v['nb_clients'],
                                    '% du Total': f"{v['pourcentage_total']}%"
                                } for v in cities_analysis['moyenne']])
                                
                                st.dataframe(moyenne_df, use_container_width=True)
                                
                                # Graphique en barres
                                fig_bar = px.bar(
                                    moyenne_df, 
                                    x='Ville', 
                                    y='Nb Clients',
                                    title="Répartition des clients - Villes à concentration moyenne",
                                    color_discrete_sequence=['#FF8C00']
                                )
                                fig_bar.update_layout(xaxis_tickangle=-45)
                                st.plotly_chart(fig_bar, use_container_width=True)
                                
                                st.markdown("""
                                **💡 Recommandations :**
                                - Marchés **équilibrés** avec potentiel d'optimisation
                                - **Analyse** des facteurs de performance
                                - **Test** de nouvelles approches commerciales
                                - **Benchmark** avec les villes à forte concentration
                                - **Actions** ciblées pour augmenter la part de marché
                                """)
                            else:
                                st.info("Aucune ville à concentration moyenne identifiée.")
                        
                        with tab4:
                            st.subheader("🟡 Villes à Faible Concentration")
                            if cities_analysis['faible']:
                                faible_df = pd.DataFrame([{
                                    'Ville': v['ville'],
                                    'Nb Clients': v['nb_clients'],
                                    '% du Total': f"{v['pourcentage_total']}%"
                                } for v in cities_analysis['faible']])
                                
                                st.dataframe(faible_df, use_container_width=True)
                                
                                # Graphique en barres
                                fig_bar = px.bar(
                                    faible_df, 
                                    x='Ville', 
                                    y='Nb Clients',
                                    title="Répartition des clients - Villes à faible concentration",
                                    color_discrete_sequence=['#FFD700']
                                )
                                fig_bar.update_layout(xaxis_tickangle=-45)
                                st.plotly_chart(fig_bar, use_container_width=True)
                                
                                st.markdown("""
                                **💡 Recommandations :**
                                - **Opportunités** de développement importantes
                                - **Étude de marché** pour comprendre les freins
                                - **Adaptation** de l'offre aux spécificités locales
                                - **Prospection** renforcée
                                - **Partenariats** locaux pour accélérer la pénétration
                                """)
                            else:
                                st.info("Aucune ville à faible concentration identifiée.")
                        
                        with tab5:
                            st.subheader("🟢 Villes à Très Faible Concentration")
                            if cities_analysis['tres_faible']:
                                tres_faible_df = pd.DataFrame([{
                                    'Ville': v['ville'],
                                    'Nb Clients': v['nb_clients'],
                                    '% du Total': f"{v['pourcentage_total']}%"
                                } for v in cities_analysis['tres_faible']])
                                
                                st.dataframe(tres_faible_df, use_container_width=True)
                                
                                # Graphique en barres
                                fig_bar = px.bar(
                                    tres_faible_df, 
                                    x='Ville', 
                                    y='Nb Clients',
                                    title="Répartition des clients - Villes à très faible concentration",
                                    color_discrete_sequence=['#90EE90']
                                )
                                fig_bar.update_layout(xaxis_tickangle=-45)
                                st.plotly_chart(fig_bar, use_container_width=True)
                                
                                st.markdown("""
                                **💡 Recommandations :**
                                - Marchés **émergents** ou **difficiles**
                                - **Analyse coût/bénéfice** approfondie
                                - **Stratégie** de pénétration à long terme
                                - **Veille concurrentielle** accrue
                                - **Innovation** dans l'approche commerciale
                                - Considérer le **regroupement** avec des zones voisines
                                """)
                            else:
                                st.info("Aucune ville à très faible concentration identifiée.")
                        
                        # Graphiques de synthèse
                        st.subheader("📊 Graphiques de Synthèse")
                        
                        col1, col2 = st.columns(2)
                        
                        with col1:
                            # Répartition par catégorie de concentration
                            concentration_counts = {
                                'Très Forte': len(cities_analysis['tres_forte']),
                                'Forte': len(cities_analysis['forte']),
                                'Moyenne': len(cities_analysis['moyenne']),
                                'Faible': len(cities_analysis['faible']),
                                'Très Faible': len(cities_analysis['tres_faible'])
                            }
                            
                            fig_pie = px.pie(
                                values=list(concentration_counts.values()),
                                names=list(concentration_counts.keys()),
                                title="Répartition des Villes par Niveau de Concentration",
                                color_discrete_map={
                                    'Très Forte': '#8B0000',
                                    'Forte': '#FF0000',
                                    'Moyenne': '#FF8C00',
                                    'Faible': '#FFD700',
                                    'Très Faible': '#90EE90'
                                }
                            )
                            st.plotly_chart(fig_pie, use_container_width=True)
                        
                        with col2:
                            # Distribution du nombre de clients
                            fig_hist = px.histogram(
                                villes_df,
                                x='nb_clients',
                                nbins=20,
                                title="Distribution du Nombre de Clients par Ville",
                                labels={'nb_clients': 'Nombre de Clients', 'count': 'Nombre de Villes'},
                                color_discrete_sequence=['#1f77b4']
                            )
                            fig_hist.add_vline(
                                x=cities_analysis['statistiques']['moyenne_clients_par_ville'],
                                line_dash="dash",
                                line_color="red",
                                annotation_text="Moyenne"
                            )
                            st.plotly_chart(fig_hist, use_container_width=True)
                        
                        # Tableau de synthèse final
                        st.subheader("📋 Synthèse Exécutive")
                        
                        # Calculer les pourcentages de clients par catégorie
                        total_clients = cities_analysis['statistiques']['total_clients']
                        
                        clients_par_categorie = {
                            'Très Forte': sum(v['nb_clients'] for v in cities_analysis['tres_forte']),
                            'Forte': sum(v['nb_clients'] for v in cities_analysis['forte']),
                            'Moyenne': sum(v['nb_clients'] for v in cities_analysis['moyenne']),
                            'Faible': sum(v['nb_clients'] for v in cities_analysis['faible']),
                            'Très Faible': sum(v['nb_clients'] for v in cities_analysis['tres_faible'])
                        }
                        
                        synthese_data = []
                        for categorie, nb_clients in clients_par_categorie.items():
                            nb_villes = concentration_counts[categorie]
                            pourcentage_clients = round((nb_clients / total_clients) * 100, 1) if total_clients > 0 else 0
                            moyenne_par_ville = round(nb_clients / nb_villes, 1) if nb_villes > 0 else 0
                            
                            synthese_data.append({
                                'Catégorie': categorie,
                                'Nb Villes': nb_villes,
                                'Nb Clients': nb_clients,
                                '% des Clients': f"{pourcentage_clients}%",
                                'Moyenne/Ville': moyenne_par_ville
                            })
                        
                        synthese_df = pd.DataFrame(synthese_data)
                        st.dataframe(synthese_df, use_container_width=True)
                        
                        # Points clés
                        st.markdown("""
                        ### 🎯 Points Clés de l'Analyse
                        
                        **🔍 Insights Stratégiques :**
                        - **Distribution** : Analysez comment vos clients se répartissent géographiquement
                        - **Concentration** : Identifiez vos marchés forts et vos opportunités de croissance
                        - **Priorités** : Orientez vos efforts commerciaux selon les catégories de villes
                        - **Optimisation** : Adaptez vos ressources selon le potentiel de chaque zone
                        
                        **📈 Actions Recommandées :**
                        1. **Consolider** les positions dans les villes à très forte concentration
                        2. **Investir** dans les villes à fort potentiel
                        3. **Analyser** les freins dans les zones à faible concentration
                        4. **Innover** dans l'approche des marchés émergents
                        """)
                    
                    else:
                        st.error("Impossible de réaliser l'analyse. Vérifiez que votre fichier contient des données de villes valides.")
            
            else:
                st.warning("Aucun résultat de carte disponible pour l'analyse.")
    
    else:
        st.info("👆 Commencez par télécharger votre fichier Excel contenant les données clients.")
        
        st.markdown("""
        ### 📋 Format de fichier attendu
        
        Votre fichier Excel doit contenir au minimum :
        - Une colonne avec les **noms des clients** (nom, client, entreprise, société...)
        - Une colonne avec les **villes** (ville, city...)
        
        Colonnes optionnelles pour les filtres :
        - **Responsable** (responsable, manager...)
        - **Collaborateur** (collaborateur, commercial...)
        - **Activité** (activité, secteur, activity...)
        - **Forme juridique** (forme, forme_juri, juridique, type...)
        - **Site** (site...)
        - **Adresse complète** (adresse, address...)
        """)

if __name__ == "__main__":
    main()
