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
# DATA IMPORTEREN EN VERWERKEN ########################
#######################################################

def get_charger_type(connections):
        ac = False
        dc = False
        for connection in connections:
            if connection is None:
                return 'AC' 
            currentId = connection.get('CurrentTypeID')
            if currentId is not None:
                if currentId < 30:
                    ac = True
                elif currentId == 30:
                    dc = True
                if ac and dc:
                    return 'AC/DC'
            else:
                return 'AC'
            if ac:
                return 'AC'
            elif dc:
                return 'DC'


# GEOGRAFISCHE DATA
@st.cache_data
def load_geo_data():

    ocm = r.get('https://api.openchargemap.io/v3/poi/?output=json&countrycode=NL&maxresults=100000&compact=true&verbose=false&key=93b912b5-9d70-4b1f-960b-fb80a4c9c017')
    df_ocm = pd.DataFrame(json.loads(ocm.text))

    useful = ['ID','Latitude','Longitude','OperatorID','UsageCost','Connections','NumberOfPoints']

    df_address = pd.json_normalize(df_ocm['AddressInfo'])[['Latitude','Longitude']]
    df_ocm = pd.concat([df_ocm,df_address],axis=1)
    df_ocm = df_ocm[useful]

    df_ocm['Type'] = df_ocm['Connections'].apply(get_charger_type)

    inwoners_gemeente = pd.read_csv('inwonertal_gemeente.csv',sep=';',usecols=['Naam_2','Inwonertal_54'])
    inwoners_gemeente = inwoners_gemeente.rename(columns={'Naam_2': 'name',
                                'Inwonertal_54': 'Inwonertal'})
    inwoners_gemeente['name'] = inwoners_gemeente['name'].str.strip()

    inwoners_provincie = pd.read_csv('inwonertal_provincie.csv',sep=';')
    inwoners_provincie['name'] = inwoners_provincie['name'].str.strip()

    # GeoDataFrames
    laders = gpd.GeoDataFrame(df_ocm, geometry=gpd.points_from_xy(df_ocm.Longitude, df_ocm.Latitude), crs="EPSG:4326")
    gemeenten = gpd.read_file('gemeenten2.json').to_crs('EPSG:4326')
    provincies = gpd.read_file('provincies.geojson').to_crs('EPSG:4326')
    # Spatial joins
    laders_gemeente = gpd.sjoin(laders, gemeenten, how='inner', predicate='within')
    laders_provincie = gpd.sjoin(laders, provincies, how='inner', predicate='within')

    ladercount_gemeente = laders_gemeente.groupby("name")['NumberOfPoints'].sum().reset_index(name="Aantal")
    ladercount_provincie = laders_provincie.groupby("name")['NumberOfPoints'].sum().reset_index(name="Aantal")

    # MERGES
    gemeenten = gemeenten.merge(ladercount_gemeente, on='name', how='left')
    provincies = provincies.merge(ladercount_provincie, on='name', how='left')
    gemeenten = gemeenten.merge(inwoners_gemeente, on='name', how='outer')
    provincies = provincies.merge(inwoners_provincie, on='name', how='outer')
    
    # Feature engineering
    gemeenten["Oppervlak"] = gemeenten.to_crs("EPSG:3857").area / 10**6
    gemeenten['Dichtheid_Inwoners'] = gemeenten['Aantal']/gemeenten['Inwonertal']*1000
    gemeenten['Dichtheid_Oppervlak'] = gemeenten['Aantal']/gemeenten['Oppervlak']

    provincies["Oppervlak"] = provincies.to_crs("EPSG:3857").area / 10**6
    provincies['Dichtheid_Inwoners'] = provincies['Aantal']/provincies['Inwonertal']*1000
    provincies['Dichtheid_Oppervlak'] = provincies['Aantal']/provincies['Oppervlak']



    return gemeenten, provincies, laders_gemeente

    #df_ocm.to_excel('jan.xlsx')

    # RDW DATA
    # rdw = r.get()
    # df_rdw = pd.DataFrame(json.loads(rdw.text))

    # LAADPAALDATA
    #df_charging = pd.read_csv('laadpaaldata.csv')



##########################################

def create_map(use_log_scale, density_type, df):
    m = folium.Map(location=[52.3676, 4.9041], zoom_start=7, min_zoom=7)
    
    if density_column not in df.columns:
        raise ValueError(f"Column '{density_column}' not found in the data")
    
    if use_log_scale:
        df[f'log_{density_type}'] = np.log(df[density_type])
        color_column = f'log_{density_type}'
        legend_name = f'Log({density_type})'
    else:
        color_column = density_type
        legend_name = density_type

    choropleth = folium.Choropleth(
        geo_data=df,
        name='choropleth',
        data=df,
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


#############################################
# STREAMLIT APP #############################
#############################################
st.set_page_config(
    page_title="EV Charger Density",
    layout="wide"
)

gemeenten, provincies, laders_gemeente = load_geo_data()\

print(provincies.head())

st.title("EV Evaluatie Dashboard")

tab1, tab2, tab3 = st.tabs(["Kaart & Statistieken", "Laadprofiel", "Autoverkoop"])

with tab1:
    st.header('EV Laadpunten in Nederland')

    # Create a container for the controls and map
    with st.container():
        # Create three columns for the controls
        col1, col2 = st.columns(2)

        with col1:
            button1, button2, button3 = st.columns(3)
            with button1:
                region_type = st.radio('Region Type', ['Gemeenten', 'Provincies'], key='region_type')
                show_gemeenten = region_type == 'Gemeenten'
            with button2: 
                scale_type = st.radio('Scale Type', ['Linear Scale', 'Log Scale'], key='scale_type')
                use_log_scale = scale_type == 'Log Scale'
            with button3:
                density_type = st.radio('Density Type', ['Inwonertal', 'Oppervlak'], key='density_type')
                density_column = 'Dichtheid_Inwoners' if density_type == 'Inwonertal' else 'Dichtheid_Oppervlak'
        # Display the selected dataframe without the geometry column
        d, e = st.columns(2)
        with d:

            st.subheader(f"Dichtheid Laadpalen per {region_type}")
            current_df = gemeenten if show_gemeenten else provincies

            # Create and display the map
            map = create_map(use_log_scale, density_column, current_df)
            folium_static(map)
        with e:
            st.subheader("Landelijke statistieken")
            st.write("Nederland is misschien een klein kikkerlandje. Echter zijn we echte pioniers op het gebied van laadinfrastructuur.\n"
                     "In Nederland hebben we:")
            aantal, dichtheid, punten, ac, dc = st.columns(5)
            with aantal:
                st.metric(value=f"{gemeenten["Aantal"].sum()}", label="Laadpalen")
            with dichtheid:
                st.metric(value=f"{(gemeenten["Aantal"].sum()/gemeenten["Inwonertal"].sum()*1000):.2f}", label="Laadpalen / 1000 inwoners")
            with punten:
                st.metric(value=f"{laders_gemeente["Type"].count()}", label="Laadpunten")
            with ac:
                st.metric(value=f"{laders_gemeente["Type"].value_counts().get('AC',0)}", label="Waarvan AC")
            with dc:
                st.metric(value=f"{laders_gemeente["Type"].value_counts().get('DC',0)}", label="Waarvan DC")
            st.subheader("Gemeentelijke statistieken")
            gemeente_names = sorted(gemeenten['name'].unique())
            selected_gemeente = st.selectbox("Selecteer een Gemeente", gemeente_names)
            
            gemeente_data = gemeenten[gemeenten['name'] == selected_gemeente]
            type_laders = laders_gemeente[laders_gemeente['name'] == selected_gemeente]['Type']
            a,f,b,c = st.columns(4)
            with a:
                st.metric("Totaal aantal laders", f"{int(gemeente_data['Aantal'])}")
            with f:
                st.metric("Laadpunten", f"{type_laders.count()}")
            with b:
                st.metric("Dichtheid laadpalen (per km²)", f"{float(gemeente_data['Dichtheid_Oppervlak']):.2f}")
            with c:
                st.metric("Dichtheid laadpalen (per 1000 inwoners)", f"{float(gemeente_data['Dichtheid_Inwoners']):.2f}")

            ac, dc, x, y = st.columns(4)
            with ac:
                st.metric("AC", f"{type_laders.value_counts().get('AC', 0)}")
            with dc:
                st.metric("DC", f"{type_laders.value_counts().get('DC', 0)}")

    st.subheader(f'{region_type} Ranglijst')

    col4, col1, col2, col3 = st.columns(4)

    with col4: 
        ranking_type = st.radio('Ranking', ['Top 5', 'Bottom 5'], key='ranking_type')
        show_top = ranking_type == 'Top 5'

    with col1:
        st.write(f"{ranking_type} Aantal laders")
        aantal_sorted = current_df.sort_values(by='Aantal', ascending=not show_top)
        top_aantal = aantal_sorted[['name', 'Aantal']].head()
        top_aantal.columns = ['Name', 'Aantal laders']
        st.dataframe(top_aantal.set_index('Name'))

    with col2:
        st.write(f"{ranking_type} Laders per Oppervlak (km2)")
        dichtheid_opp_sorted = current_df.sort_values(by='Dichtheid_Oppervlak', ascending=not show_top)
        top_dichtheid_opp = dichtheid_opp_sorted[['name', 'Dichtheid_Oppervlak']].head()
        top_dichtheid_opp.columns = ['Name', 'Laadpalen per km2)']
        st.dataframe(top_dichtheid_opp.set_index('Name'))

    with col3:
        st.write(f"{ranking_type} Laders per 1000 inwoners")
        dichtheid_inw_sorted = current_df.sort_values(by='Dichtheid_Inwoners', ascending=not show_top)
        top_dichtheid_inw = dichtheid_inw_sorted[['name', 'Dichtheid_Inwoners']].head()
        top_dichtheid_inw.columns = ['Name', 'Laadpalen per 1000 inwoners']
        st.dataframe(top_dichtheid_inw.set_index('Name'))

with tab2:
    st.header("Charging Profile")

with tab3:
    st.header("Car Sales")
    df['datum_eerste_tenaamstelling_in_nederland'] = pd.to_datetime(df['datum_eerste_tenaamstelling_in_nederland'])
    df['hybride'] = df['klasse_hybride_elektrisch_voertuig'].notnull()

    df['brandstof_omschrijving'] = df.apply(lambda row: 'Hybride' if row['hybride'] else row['brandstof_omschrijving'], axis=1)
    # Filter ongewenste brandstofcategorieën eruit
    filtered_df = df[~df['brandstof_omschrijving'].isin(['LPG', 'Alcohol', 'CNG', 'Waterstof'])]

    # Delete rijen zonder geldige datum
    filtered_df = filtered_df.dropna(subset=['datum_eerste_tenaamstelling_in_nederland'])

    # Nieuwe kolom met alleen de maand en het jaar 
    filtered_df['inschrijvingsmaand'] = filtered_df['datum_eerste_tenaamstelling_in_nederland'].dt.to_period('M').astype(str)

    # multiselect widget voor brandstofcategorieën
    brandstof_opties = filtered_df['brandstof_omschrijving'].unique()
    geselecteerde_brandstof = st.multiselect('Selecteer brandstofcategorie', brandstof_opties, default=brandstof_opties)

    filtered_df = filtered_df[filtered_df['brandstof_omschrijving'].isin(geselecteerde_brandstof)]

    # Groeperen per brandstofcategorie en per maand en cumulatief optellen
    cumulative_df = filtered_df.groupby(['inschrijvingsmaand', 'brandstof_omschrijving']).size().groupby(level=1).cumsum().reset_index(name='aantal_voertuigen')

    fig = px.line(cumulative_df,
                x='inschrijvingsmaand',
                y='aantal_voertuigen',
                color='brandstof_omschrijving',
                labels={'inschrijvingsmaand': 'Maand van inschrijving', 'aantal_voertuigen': 'Cumulatief aantal voertuigen'},
                title='Cumulatief aantal voertuigen per maand per brandstofcategorie',
                color_discrete_sequence=['orange', 'red', 'skyblue', 'lightgreen'])

    st.plotly_chart(fig)
