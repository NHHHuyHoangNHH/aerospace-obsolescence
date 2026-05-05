import csv, random
from datetime import datetime, timedelta
random.seed(42)

CATEGORIES = ['Avionics','Hydraulics','Landing Gear','Engine Components','Electrical Systems','Fuel Systems','Navigation','Communication','Structural','Environmental Control','Flight Controls','Lighting']
SUPPLIERS = ['Honeywell Aerospace','Raytheon Technologies','GE Aviation','Parker Hannifin','Safran Group','BAE Systems','L3 Technologies','TransDigm Group','Heico Corporation','Moog Inc.','Curtiss-Wright','Ducommun','Kaman Aerospace','Triumph Group','Spirit AeroSystems']
REGIONS = ['North America','Europe','Asia Pacific','Middle East','Latin America']
AIRCRAFT = ['Boeing C-17 Globemaster','Boeing 737','Boeing 747','Boeing 777','Boeing 787 Dreamliner','Airbus A320','Airbus A380','F/A-18','C-130 Hercules','AH-64 Apache']
LIFECYCLE = ['Active','Active','Active','End-of-Life','Obsolete','Phased-Out','Discontinued']
OBS_REASONS = ['Supplier discontinued production','Component no longer meets MIL-SPEC','Semiconductor shortage','Manufacturer acquired, line discontinued','Replaced by newer technology','RoHS non-compliance','Lead-free transition','Single-source supplier exit','ITAR restriction changes','Market demand too low']
PART_NAMES = {'Avionics':['Flight Management Computer','Inertial Reference Unit','Air Data Module','Digital Flight Data Recorder','Cockpit Display Unit','GPS Receiver Module'],'Hydraulics':['Hydraulic Pump Assembly','Actuator Valve','Pressure Regulator','Hydraulic Filter','Ram Air Turbine','Accumulator Assembly'],'Landing Gear':['Main Gear Strut','Nose Wheel Assembly','Brake Assembly','Gear Retraction Motor','Shimmy Damper','Torque Link'],'Engine Components':['Turbine Blade Set','Fuel Nozzle Assembly','Oil Pump','Combustion Chamber Liner','Compressor Disc','Thrust Reverser Actuator'],'Electrical Systems':['Power Distribution Unit','Circuit Breaker Panel','Bus Controller','Generator Control Unit','Battery Relay Assembly','Wiring Harness'],'Fuel Systems':['Fuel Quantity Indicator','Fuel Boost Pump','Fuel Control Unit','Cross-Feed Valve','Fuel Pressure Transmitter','Fuel Tank Liner'],'Navigation':['VOR Receiver','ILS Localizer','TCAS Computer','ADS-B Transponder','Radio Altimeter','Weather Radar Antenna'],'Communication':['VHF Transceiver','HF Radio Unit','SATCOM Unit','Interphone System','ELT','Data Link Modem'],'Structural':['Fuselage Frame Section','Wing Spar Assembly','Bulkhead Fitting','Skin Panel Segment','Stringer Assembly','Floor Beam'],'Environmental Control':['Air Cycle Machine','Temp Control Valve','Cabin Pressure Controller','Recirculation Fan','Ozone Converter','Water Separator'],'Flight Controls':['Aileron Actuator','Elevator Servo','Rudder Pedal Assembly','Flap Drive Motor','Spoiler Panel','Trim Tab Actuator'],'Lighting':['Landing Light Assembly','Anti-Collision Beacon','Navigation Light','Cockpit Flood Light','Emergency Exit Light','Formation Light']}

def rdate(y1, y2):
    d = datetime(y1,1,1) + timedelta(days=random.randint(0,(datetime(y2,12,31)-datetime(y1,1,1)).days))
    return d.strftime('%Y-%m-%d')

rows = []
for i in range(5000):
    cat = random.choice(CATEGORIES)
    status = random.choice(LIFECYCLE)
    is_obs = 1 if status in ['End-of-Life','Obsolete','Phased-Out','Discontinued'] else 0

    # ── Ranges overlap nhau để model không thể dùng 1 feature phân loại perfect ──
    if is_obs:
        # Obsolete: thiên về cũ/lead time dài, nhưng vẫn có overlap với Active
        mfg_year  = random.randint(1985, 2015)   # overlap 2005–2015 với Active
        lead_time = random.randint(90, 365)       # overlap 90–180 với Active
        stock     = random.randint(0, 200)        # overlap 50–200 với Active
        n_alt     = random.randint(0, 3)          # overlap 1–3 với Active
        alt_avail = random.choices(['No','Partial','Yes'], weights=[0.55, 0.35, 0.10])[0]
        # Score phụ thuộc nhiều yếu tố, không chỉ status
        base_score = 0.45
        base_score += 0.15 if mfg_year < 2000 else 0.05
        base_score += 0.15 if lead_time > 270 else 0.05
        base_score += 0.10 if stock < 30 else 0.0
        base_score += 0.10 if n_alt == 0 else 0.0
        base_score += random.uniform(-0.08, 0.08)   # noise
        score = round(min(max(base_score, 0.35), 1.0), 2)
        obs_reason = random.choice(OBS_REASONS)
        exp_date = rdate(2020, 2027)
    else:
        # Active: thiên về mới/lead time ngắn, nhưng vẫn có overlap
        mfg_year  = random.randint(2000, 2023)   # overlap 2000–2015 với Obsolete
        lead_time = random.randint(14, 270)      # overlap 90–270 với Obsolete
        stock     = random.randint(20, 600)      # overlap 20–200 với Obsolete
        n_alt     = random.randint(0, 6)         # overlap 0–3 với Obsolete
        alt_avail = random.choices(['Yes','Partial','No'], weights=[0.55, 0.35, 0.10])[0]
        base_score = 0.20
        base_score += 0.10 if mfg_year < 2008 else 0.0
        base_score += 0.10 if lead_time > 180 else 0.0
        base_score += 0.08 if stock < 40 else 0.0
        base_score += 0.08 if n_alt == 0 else 0.0
        base_score += random.uniform(-0.08, 0.08)   # noise
        score = round(min(max(base_score, 0.0), 0.55), 2)
        obs_reason = ''
        exp_date = ''

    prefix = random.choice(['BCA','AES','MIL','GEN','TRD'])
    rows.append({
        'part_id': f'{prefix}-{i+1:05d}',
        'part_name': f"{random.choice(PART_NAMES[cat])} (Rev {random.randint(1,9)})",
        'category': cat,
        'aircraft_model': random.choice(AIRCRAFT),
        'supplier': random.choice(SUPPLIERS),
        'region': random.choice(REGIONS),
        'manufacture_year': mfg_year,
        'lead_time_days': lead_time,
        'stock_level': stock,
        'unit_price_usd': round(random.uniform(50, 150000), 2),
        'last_order_date': rdate(2018, 2024),
        'last_reviewed_date': rdate(2022, 2024),
        'lifecycle_status': status,
        'criticality': random.choices(['High','Medium','Low'], weights=[0.2,0.5,0.3])[0],
        'mtbf_hours': random.randint(1000, 50000),
        'num_alternative_suppliers': n_alt,
        'alternative_part_available': alt_avail,
        'obsolescence_score': score,
        'obsolescence_label': is_obs,
        'obsolescence_reason': obs_reason,
        'expected_obsolescence_date': exp_date,
    })

with open('/media/ctuav/corsair-ssd/hoang.nguyen/test/data/raw/aerospace_parts_dataset.csv','w',newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader(); w.writerows(rows)

obs = sum(1 for r in rows if r['obsolescence_label']==1)
print(f'Generated {len(rows)} rows — Obsolete: {obs} ({obs/len(rows)*100:.1f}%)')

# Kiểm tra overlap
active_lead  = [r['lead_time_days'] for r in rows if r['obsolescence_label']==0]
obs_lead     = [r['lead_time_days'] for r in rows if r['obsolescence_label']==1]
active_mfg   = [r['manufacture_year'] for r in rows if r['obsolescence_label']==0]
obs_mfg      = [r['manufacture_year'] for r in rows if r['obsolescence_label']==1]
print(f'Active   lead_time: {min(active_lead)}–{max(active_lead)}, avg={sum(active_lead)//len(active_lead)}')
print(f'Obsolete lead_time: {min(obs_lead)}–{max(obs_lead)}, avg={sum(obs_lead)//len(obs_lead)}')
print(f'Active   mfg_year:  {min(active_mfg)}–{max(active_mfg)}, avg={sum(active_mfg)//len(active_mfg)}')
print(f'Obsolete mfg_year:  {min(obs_mfg)}–{max(obs_mfg)}, avg={sum(obs_mfg)//len(obs_mfg)}')