import pandas as pd 
import geopandas as gpd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import st_folium, folium_static
import requests as r
import seaborn as sns
from pprint import pprint
import json
import folium
import matplotlib.pyplot as plt


#######################################################
# DATA IMPORTEREN #####################################
#######################################################

# OPEN CHARGE MAP DATA
ocm = r.get('https://api.openchargemap.io/v3/poi/?output=json&countrycode=NL&maxresults=100000&compact=true&verbose=false&key=93b912b5-9d70-4b1f-960b-fb80a4c9c017')
df_ocm = pd.DataFrame(json.loads(ocm.text))
#df_ocm.to_excel('jan.xlsx')

# RDW DATA
# rdw = r.get()
# df_rdw = pd.DataFrame(json.loads(rdw.text))

# LAADPAALDATA
#df_charging = pd.read_csv('laadpaaldata.csv')

# INWONERTAL
inwonertal = pd.read_csv('inwonertal.csv',sep=';',usecols=['Naam_2','Inwonertal_54'])
inwonertal = inwonertal.rename(columns={'Naam_2': 'name',
                                'Inwonertal_54': 'Inwonertal'})
inwonertal['name'] = inwonertal['name'].str.strip()
print(inwonertal['name'].head())
######################################################
# DATA INSPECTEREN ###################################
######################################################

# OCM
print(df_ocm.head(5))
print(df_ocm.columns)
# Lijst met zinvolle kolommen
useful = ['ID','Latitude','Longitude','OperatorID','UsageCost','Connections','NumberOfPoints']
df_address = pd.json_normalize(df_ocm['AddressInfo'])[['Latitude','Longitude']]
df_ocm = pd.concat([df_ocm,df_address],axis=1)
df_ocm = df_ocm[useful]
print(df_ocm.isnull().sum())
#df_connections = pd.json_normalize(df_ocm['Connections'], sep='_')
#df_connectors = pd.DataFrame()
# for col in range(0,11):
#     print(col, type(col))
#     df_col = pd.json_normalize(df_connections[col])[['ConnectionTypeID', 'PowerKW','CurrentTypeID']]

    #pd.concat([df_connectors,df_col])
#df_connectors = pd.json_normalize(df_connections[0])

# GEMEENTE EN PRONVICIE DATA
gemeenten = gpd.read_file('gemeenten2.geojson')
provincies = gpd.read_file('provincies.geojson')

gemeenten.to_crs("EPSG:4326")

# Laders GeoDataFrame met geometrie
laders = gpd.GeoDataFrame(df_ocm, geometry=gpd.points_from_xy(df_ocm.Longitude, df_ocm.Latitude), crs="EPSG:4326")
 
laders_per_gemeente = gpd.sjoin(laders, gemeenten, how='inner', predicate='within')
ladersaantal = laders_per_gemeente.groupby("name")['NumberOfPoints'].sum().reset_index(name="Aantal")

# Gemeenten en ladersaantal mergen op naam.
gemeenten = gemeenten.merge(ladersaantal, on='name', how='left')
print("gemeenten name dtype:", gemeenten['name'].unique())
print("inwonertal name dtype:", inwonertal['name'].unique())
inwonertal = inwonertal[inwonertal['name'].isin(gemeenten['name'].unique())]
print(inwonertal['name'].unique())
gemeenten = gemeenten.merge(inwonertal, on='name', how='outer')
print(gemeenten.info())
gemeenten["Oppervlak"] = gemeenten.to_crs("EPSG:3857").area / 10**6
gemeenten['Dichtheid_Inwoners'] = gemeenten['Aantal']/gemeenten['Inwonertal']*1000
gemeenten['Dichtheid_Oppervlak'] = gemeenten['Aantal']/gemeenten['Oppervlak']

print(gemeenten.info())

def create_map(use_log_scale, density_type):
    m = folium.Map(location=[52.3676, 4.9041], zoom_start=7)
    
    if use_log_scale:
        gemeenten[f'log_{density_type}'] = np.log(gemeenten[density_type])
        color_column = f'log_{density_type}'
        legend_name = f'Log({density_type})'
    else:
        color_column = density_type
        legend_name = density_type

    choropleth = folium.Choropleth(
        geo_data=gemeenten,
        name='choropleth',
        data=gemeenten,
        columns=['name', color_column],
        key_on='feature.properties.name',
        fill_color='YlOrRd',
        fill_opacity=0.7,
        line_opacity=0.2,
        legend_name=legend_name,
        smooth_factor=0
    ).add_to(m)

    choropleth.geojson.add_child(
        folium.features.GeoJsonTooltip(
            fields=['name', 'Aantal', 'Dichtheid_Oppervlak', 'Dichtheid_Inwoners'],
            aliases=['Gemeente:', 'Aantal Chargers:', 'Dichtheid per km²:', 'Dichtheid per 1000 inwoners:'],
            localize=True,
            sticky=False,
            labels=True
        )
    )

    folium.LayerControl().add_to(m)
    return m

# Streamlit app
st.title('Charger Density Map')

# Create two columns for the switches
col1, col2 = st.columns(2)

# Switch for log scale
with col1:
    if 'log_scale' not in st.session_state:
        st.session_state.log_scale = False
    use_log_scale = st.checkbox('Use Log Scale', value=st.session_state.log_scale)
    if use_log_scale != st.session_state.log_scale:
        st.session_state.log_scale = use_log_scale

# Switch for density type
with col2:
    density_type = st.radio('Density Type', ['Dichtheid_Oppervlak', 'Dichtheid_Inwoners'])

map = create_map(st.session_state.log_scale, density_type)
folium_static(map)

st.subheader('Gemeenten Ranking')

# Add a toggle for top/bottom 5
if 'show_top' not in st.session_state:
    st.session_state.show_top = True

show_top = st.button('Toggle Top/Bottom 5')
if show_top:
    st.session_state.show_top = not st.session_state.show_top

ranking_text = "Top 5" if st.session_state.show_top else "Bottom 5"
st.write(f"Currently showing: {ranking_text} Gemeenten")

col1, col2, col3 = st.columns(3)

with col1:
    st.write(f"{ranking_text} by Number of Chargers")
    aantal_sorted = gemeenten.sort_values(by='Aantal', ascending=not st.session_state.show_top)
    top_aantal = aantal_sorted[['name', 'Aantal']].head()
    top_aantal.columns = ['Gemeente', 'Number of Chargers']
    st.dataframe(top_aantal.reset_index(drop=True))

with col2:
    st.write(f"{ranking_text} by Charger Density (per km²)")
    dichtheid_opp_sorted = gemeenten.sort_values(by='Dichtheid_Oppervlak', ascending=not st.session_state.show_top)
    top_dichtheid_opp = dichtheid_opp_sorted[['name', 'Dichtheid_Oppervlak']].head()
    top_dichtheid_opp.columns = ['Gemeente', 'Charger Density (per km²)']
    st.dataframe(top_dichtheid_opp.reset_index(drop=True))

with col3:
    st.write(f"{ranking_text} by Charger Density (per 1000 inhabitants)")
    dichtheid_inw_sorted = gemeenten.sort_values(by='Dichtheid_Inwoners', ascending=not st.session_state.show_top)
    top_dichtheid_inw = dichtheid_inw_sorted[['name', 'Dichtheid_Inwoners']].head()
    top_dichtheid_inw.columns = ['Gemeente', 'Charger Density (per 1000 inhabitants)']
    st.dataframe(top_dichtheid_inw.reset_index(drop=True))