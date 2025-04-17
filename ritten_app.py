import streamlit as st
import pandas as pd
import gspread
import json
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta

# === SETTINGS ===
SHEET_NAME = "Rittenregistratie"  # pas aan als je een andere sheetnaam gebruikt

# === Google Sheets Connectie ===
def connect_to_sheets():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
    client = gspread.authorize(creds)
    return client

client = connect_to_sheets()
sheet_ritten = client.open(SHEET_NAME).worksheet("Ritten")
sheet_tarieven = client.open(SHEET_NAME).worksheet("Tarieven")

# === Data laden ===
def load_ritten():
    data = sheet_ritten.get_all_records()
    return pd.DataFrame(data)

def load_tarieven():
    data = sheet_tarieven.get_all_values()
    #st.write("📋 Sheet RAW data:", data)

    if not data:
        st.warning("⚠️ Het tabblad 'Tarieven' is leeg of onjuist.")
        return pd.DataFrame()

    headers = data[0]
    rows = data[1:]
    df = pd.DataFrame(rows, columns=headers)

    #st.write("🔎 Headers gedetecteerd:", headers)
    return df


# === Tarieven ophalen per datum ===
def get_tarief_for_date(datum):
    tarieven = load_tarieven()
    tarieven["Vanaf"] = pd.to_datetime(tarieven["Vanaf"], errors="coerce")  # <- fix!
    datum = pd.to_datetime(datum)
    geldig = tarieven[tarieven["Vanaf"] <= datum]
    if geldig.empty:
        return tarieven.iloc[0]
    return geldig.iloc[-1]

# === Berekening uren & totaal ===
def calculate_payment(start_time, end_time, total_km, tarief):
    try:
        start = datetime.strptime(start_time, "%H:%M")
        end = datetime.strptime(end_time, "%H:%M")
        if end < start:
            end += timedelta(days=1)
        total_hours = (end - start).total_seconds() / 3600

        surplus_hours = max(0, total_hours - 8)
        remaining_hours = total_hours - surplus_hours

        night_start = datetime.strptime("22:00", "%H:%M")
        night_end = datetime.strptime("06:00", "%H:%M") + timedelta(days=1)

        night_hours = 0
        if start < night_start and end > night_start:
            night_hours += (min(end, night_end) - night_start).total_seconds() / 3600
        elif start >= night_start or end <= night_end:
            night_hours += remaining_hours

        night_hours = max(0, min(night_hours, remaining_hours))
        normal_hours = remaining_hours - night_hours

        # 👉 fix: zorg dat alle tarieven floats zijn
        tarief = {k: float(str(v).replace(",", ".")) if k != "Vanaf" else v for k, v in tarief.items()}

        payment = (
            normal_hours * tarief["day_rate"] +
            night_hours * tarief["night_rate"] +
            surplus_hours * tarief["surplus_rate"] +
            total_km * tarief["km_rate"]
        )

        return {
            "Normale Uren": round(normal_hours, 2),
            "Nachturen": round(night_hours, 2),
            "Surplus Uren": round(surplus_hours, 2),
            "Totale Uren": round(total_hours, 2),
            "Totaal": round(payment, 2),
        }

    except Exception as e:
        st.error(f"❌ Fout bij berekening: {e}")
        return None


# === App interface ===
st.set_page_config("Rittenregistratie", layout="wide")
tab1, tab2 = st.tabs(["📋 Registratie", "⚙️ Tarieven"])

# === 📋 TAB 1: Ritregistratie ===
with tab1:
    df = load_ritten()
    st.title("🚐 Rittenregistratie")

    with st.form("toevoeg_rit", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            datum = st.date_input("Datum", datetime.today())
            klant = st.text_input("Klant")
            starttijd = st.text_input("Starttijd (HH:MM)")
        with col2:
            eindtijd = st.text_input("Eindtijd (HH:MM)")
            kilometers = st.number_input("Kilometers", min_value=0.0, format="%.2f")
            gefactureerd = st.checkbox("Gefactureerd?")

        if st.form_submit_button("Toevoegen"):
            if not klant or not starttijd or not eindtijd:
                st.error("❌ Vul alle velden in.")
            else:
                tarief = get_tarief_for_date(datum)
                result = calculate_payment(starttijd, eindtijd, kilometers, tarief)
                if result is None:
                    st.error("❌ Ongeldige tijd")
                else:
                    nieuwe_rit = [
                        datum.strftime("%Y-%m-%d"),
                        klant,
                        starttijd,
                        eindtijd,
                        kilometers,
                        "Ja" if gefactureerd else "Nee",
                        result["Normale Uren"],
                        result["Nachturen"],
                        result["Surplus Uren"],
                        result["Totale Uren"],
                        result["Totaal"]
                    ]
                    sheet_ritten.append_row(nieuwe_rit)
                    st.success("✅ Rit toegevoegd")
                    st.rerun()

    st.subheader("📄 Overzicht")

    st.divider()
    st.subheader("✏️ Rit bewerken of verwijderen")

    if df.empty:
        st.info("Er zijn nog geen ritten om te bewerken.")
    else:
        df["__label__"] = df["Datum"] + " – " + df["Klant"]
        selected_label = st.selectbox("Selecteer een rit:", df["__label__"])

        selected_index = df[df["__label__"] == selected_label].index[0]
        selected_rit = df.loc[selected_index]

        with st.form("edit_rit_form"):
            col1, col2 = st.columns(2)
            with col1:
                edit_datum = st.date_input("Datum", pd.to_datetime(selected_rit["Datum"]))
                edit_klant = st.text_input("Klant", selected_rit["Klant"])
                edit_starttijd = st.text_input("Starttijd (HH:MM)", selected_rit["Starttijd"])
            with col2:
                edit_eindtijd = st.text_input("Eindtijd (HH:MM)", selected_rit["Eindtijd"])
                edit_kilometers = st.number_input("Kilometers", value=float(selected_rit["Kilometers"]), format="%.2f")
                edit_gefactureerd = st.checkbox("Gefactureerd?", selected_rit["Gefactureerd"] == "Ja")

            col3, col4 = st.columns([2, 1])
            with col3:
                if st.form_submit_button("✅ Opslaan wijziging"):
                    tarief = get_tarief_for_date(edit_datum)
                    result = calculate_payment(edit_starttijd, edit_eindtijd, edit_kilometers, tarief)
                    if result is None:
                        st.error("❌ Ongeldige tijd")
                    else:
                        nieuwe_rit = [
                            edit_datum.strftime("%Y-%m-%d"),
                            edit_klant,
                            edit_starttijd,
                            edit_eindtijd,
                            edit_kilometers,
                            "Ja" if edit_gefactureerd else "Nee",
                            result["Normale Uren"],
                            result["Nachturen"],
                            result["Surplus Uren"],
                            result["Totale Uren"],
                            result["Totaal"]
                        ]
                        sheet_ritten.update(f"A{selected_index + 2}:K{selected_index + 2}", [nieuwe_rit])
                        st.success("✅ Rit aangepast")
                        st.rerun()

            with col4:
                if st.form_submit_button("🗑️ Verwijder rit"):
                    if st.checkbox("⚠️ Zeker weten?"):
                        if st.checkbox("⚠️ Echt zeker?"):
                            sheet_ritten.delete_rows(selected_index + 2)
                            st.success("🗑️ Rit verwijderd")
                            st.rerun()

    st.dataframe(df, use_container_width=True)

# === ⚙️ TAB 2: Tarievenbeheer ===
with tab2:
    st.title("⚙️ Tarieven beheren")

    tarieven_df = load_tarieven()
    st.dataframe(tarieven_df, use_container_width=True)

    st.subheader("➕ Nieuw tarief")
    with st.form("nieuw_tarief"):
        vanaf = st.date_input("Geldig vanaf", datetime.today())
        col1, col2 = st.columns(2)
        with col1:
            day = st.number_input("Dagtarief", value=14.45, step=0.01)
            night = st.number_input("Nachttarief", value=15.57, step=0.01)
        with col2:
            surplus = st.number_input("Surplustarief", value=19.52, step=0.01)
            km = st.number_input("Km-vergoeding", value=0.29, step=0.01)

        if st.form_submit_button("Toevoegen tarief"):
            bestaande = pd.to_datetime(tarieven_df["Vanaf"], errors="coerce").dt.normalize()
            if pd.to_datetime(vanaf).normalize() in bestaande.values:
                st.warning("⚠️ Er bestaat al een tarief met deze ingangsdatum.")
            else:
                nieuwe_tarief = [
                    vanaf.strftime("%Y-%m-%d"),
                    day,
                    night,
                    surplus,
                    km
                ]
                sheet_tarieven.append_row(nieuwe_tarief)
                st.success("✅ Nieuw tarief toegevoegd")
                st.rerun()
