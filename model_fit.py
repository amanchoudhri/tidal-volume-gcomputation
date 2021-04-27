from pathlib import Path

import numpy as np
import pandas as pd

CWD = Path().absolute()
END_HOUR = 96

df = pd.read_csv(CWD / 'driving_pressure_dataset.csv')

# ---- create / rename useful columns ----
df['driving_pressure'] = df['plateau_pressure'] - df['peep_set']
# whether the driving pressure was measured at a given time point
df['driving_pressure_meas'] = (df['plateau_pressure_meas'] == True) & (df['peep_set_meas'] == True)
# whether the driving pressure was measured at time t - 1
df['last_driving_pressure_meas'] = (df['last_plateau_pressure_meas'] == True) & (df['last_peep_set_meas'] == True)
# rename tidal volume columns
df['imputed_TV_standardized_meas'] = df['tidal_volume_set_meas']
df['last_imputed_TV_standardized_meas'] = df['last_tidal_volume_set_meas']


def _group_by_stay(*columns: str):
    grouped = df.groupby('stay_id', axis='rows', group_keys=False)
    if not columns:
        return grouped
    return grouped[list(columns)]

def get_last(column: str):
    """Convert each row of a given column into storing the LAST measurement (the value at time t - 1)."""
    grouped = _group_by_stay(column)
    return grouped.shift(periods=1)

def time_since_last(column: str):
    """# Get time since last measurement, where group is a column of bools representing whether a meas was taken."""
    grouped = _group_by_stay(column)
    def _handle_group(g):
        not_measured = ~g
        # Take the cumulative sum of the not_measured column
        # This gives us a value that increases only when not_measured is true
        cum_sum = not_measured.cumsum()
        # Create a column tracking the value of cum_sum at the last measurement
        cum_sum_at_last_meas = cum_sum.where(g.astype(bool)).ffill()
        # We can now subtract it from cum_sum to obtain ts_last!
        new_g = cum_sum - cum_sum_at_last_meas
        return new_g
    return grouped.transform(_handle_group)

def time_since_prev(column: str):
    """Create new column tracking the time since the previous measurement.

    Previous differs from last in one key way: when a value is measured at the current time point, LAST = 0. 
    But PREVIOUS lists the time since the measurement before the current one.
    """
    ts_last_col = column + '_ts_last'
    meas_col = column + '_meas'
    # Condition to replace with 'previous' value: if a measurement was taken at the current timestep and if study hour is > 1
    condition = (df[meas_col] == True) & (df['study_hour'] > 1)
    # Create a numpy array that tracks what the 'previous' value WOULD be at any given time point
    prev_value = np.concatenate([[np.nan], df[ts_last_col]])[:-1] + 1
    # If the condition is satisfied, replace the 'time since last' value with the new, 'time since previous', value
    new_column = np.where(condition, prev_value, df[ts_last_col])
    return pd.Series(new_column)


for p in ('driving_pressure', 'plateau_pressure'):
    # Create column tracking change in measurement from time = t - 1 to time = t
    df[p + '_change'] = df[p] - df['last_' + p]
    # Create column storing the value of the last measurement
    df['last_' + p + '_change'] = get_last(p + '_change')
    # Create column storing the time since last measurement
    df[p + '_ts_last'] = time_since_last(p + '_meas')
    # Create column storing the time since the previous measurement
    df[p+ '_ts_prev'] = time_since_prev(p)

df['peep_set_change'] = df['peep_set'] - df['last_peep_set']
df['tidal_volume_set_change'] = df['tidal_volume_set'] - df['last_tidal_volume_set']


def at_prev_dp_meas(column: str):
    """Get value of a measurement at the previous time driving pressure was measured."""
    grouped = _group_by_stay()
    def _handle_group(g):
        # Get the value at the LAST time driving pressure was measured
        at_last_dp_meas = g[column].where(g['driving_pressure_meas']).ffill()
        # Convert to value at PREVIOUS time by replacing values at timesteps when DP was measured with the proper 'previous' value
        prev_value = at_last_dp_meas.shift(periods=1)     # Track what the 'previous' value would be at any given time point
        condition = (g['driving_pressure_meas']) & (g['study_hour'] > 1)
        return at_last_dp_meas.where(condition, other=prev_value)
    return grouped.apply(_handle_group)


df['peep_set_at_prev_dp_meas'] = at_prev_dp_meas('peep_set')
df['dp_peep_change'] = df['peep_set'] - df['peep_set_at_prev_dp_meas']

df['tidal_volume_set_at_prev_dp_meas'] = at_prev_dp_meas('tidal_volume_set')
df['dp_tidal_volume_change'] = df['tidal_volume_set'] - df['tidal_volume_set_at_prev_dp_meas']

df['dp_at_prev_dp_meas'] = at_prev_dp_meas('driving_pressure')
df['dp_change_since_prev_dp_meas'] = df['driving_pressure'] - df['dp_at_prev_dp_meas']
df['last_dp_change_since_prev_dp_meas'] = get_last('dp_change_since_prev_dp_meas')

df['last_total_fluids'] = get_last('total_fluids')

df['any_rate_std'] = df['rate_std'] > 0
df['last_any_rate_std'] = get_last('any_rate_std')

df['total_rate_std'] = _group_by_stay('rate_std').cumsum()
df['last_total_rate_std'] = get_last('total_rate_std')

df = df[(df['study_started']) & (df['study_hour'] <= END_HOUR)]
df = df.sort_values(['stay_id', 'hour'])

# TODO: Implement cubic b-spline models for hour and study_hour

df['any_amount'] = df['amount'] > 0 
df['rate_std_meas'] = 1
df['any_rate_std_meas'] = 1
df['last_any_rate_std_meas'] = 1
df['amount_meas'] = 1
df['last_rate_std_meas'] = 1
df['last_amount_meas'] = 1
df['rass_min_meas'] = df['rass_meas']
df['last_rass_min_meas'] = df['last_rass_meas']

# Coviarates that are modeled separately from those in L_cont
L_dp = ['driving_pressure']
L_pf = []
L_ph = ['ph']
# Continuous covariates that PRECEDE tidal volume within the same time step causally
L_cont = [item.lower() for item in [
    "HeartRate","SysBP","DiasBP","meanbp","RespRate","TempC","rass_min", "PO2",
    "PCO2","aado2_calc","pao2fio2ratio","spo2","peep_set"
]]
# Continuous covariates that FOLLOW tidal volume causally within the same time step
L_cont2 = ['mean_airway_pressure', 'inspiratory_time', 'peak_insp_pressure']
# Non-continuous covariates that PRECEDE tidal volume within the same time step causally
L_ordinal = []
L_binary = ['any_rate_std']
L_hybrid = ['amount']

L = list(np.concatenate(
    [L_cont, L_cont2, L_binary, L_ordinal, L_hybrid, L_dp, L_pf, L_ph]
))
L_meas = [covariate + '_meas' for covariate in L]
C = ['control']
A = ['tidal_volume_set']
derived = []
Y = ['hospital_expire_flag']

# Process and remove outliers
df['amount'] = df['amount']/1000
df['last_amount'] = df['last_amount']/1000
df['total_fluids'] = df['total_fluids']/1000
df['last_total_fluids'] = df['last_total_fluids']/1000

df.loc[df['driving_pressure'] <= 0, 'driving_pressure'] = np.nan
df.loc[df['dp_change_since_prev_dp_meas'].abs() > 10, 'driving_pressure'] = np.nan
df.loc[df['dp_change_since_prev_dp_meas'].abs() > 10, 'dp_change_since_prev_dp_meas'] = np.nan

df.loc[df['meanbp'] > 200, 'meanbp'] = np.nan
df.loc[df['rr_set_set'] <= 0, 'rr_set_set'] = np.nan
df.loc[df['peak_insp_pressure'] <= 0, 'peak_insp_pressure'] = np.nan
df.loc[df['mean_airway_pressure'] <= 0, 'mean_airway_pressure'] = np.nan
df.loc[df['inspiratory_time'] <= 0, 'inspiratory_time'] = np.nan
df.loc[df['aado2_calc'] <= 0, 'aado2_calc'] = np.nan
df.loc[df['imputed_TV_standardized'] < 2, 'imputed_TV_standardized'] = np.nan
df.loc[df['imputed_TV_standardized'] > 12, 'imputed_TV_standardized'] = np.nan
df.loc[df['tidal_volume_set'] < 200, 'imputed_TV_standardized'] = np.nan
df.loc[df['tidal_volume_set'] < 200, 'imputed_TV_standardized'] = np.nan
df.loc[df['tidal_volume_set'] < 200, 'tidal_volume_set'] = np.nan

df.loc[df['plateau_pressure'] > 45, 'plateau_pressure'] = np.nan
df.loc[df['plateau_pressure_change'].abs() > 10, 'plateau_pressure'] = np.nan
df.loc[df['plateau_pressure_change'].abs() > 10, 'plateau_pressure_change'] = np.nan

condition = (np.log(df['peak_insp_pressure']) > 4) | (np.log(df['peak_insp_pressure']) < 1)
df.loc[condition, 'peak_insp_pressure'] = np.nan

df.loc[df['mean_airway_pressure'] > 50, 'mean_airway_pressure'] = np.nan
df.loc[df['inspiratory_time'] > 1.5, 'inspiratory_time'] = np.nan
df['pao2fio2ratio'] = np.minimum(df['pao2fio2ratio'], 600)

df.loc[df['last_driving_pressure'] <= 0, 'last_driving_pressure'] = np.nan
df.loc[df['last_meanbp'] > 200, 'last_meanbp'] = np.nan
df.loc[df['last_rr_set_set'] <= 0, 'last_rr_set_set'] = np.nan
df.loc[df['last_peak_insp_pressure'] <= 0, 'last_peak_insp_pressure'] = np.nan
df.loc[df['last_mean_airway_pressure'] <= 0, 'last_mean_airway_pressure'] = np.nan
df.loc[df['last_inspiratory_time'] <= 0, 'last_inspiratory_time'] = np.nan
df.loc[df['last_aado2_calc'] <= 0, 'last_aado2_calc'] = np.nan
df.loc[df['last_imputed_TV_standardized'] < 2, 'last_imputed_TV_standardized'] = np.nan
df.loc[df['last_imputed_TV_standardized'] > 12, 'last_imputed_TV_standardized'] = np.nan
df.loc[df['last_tidal_volume_set'] < 200, 'last_imputed_TV_standardized'] = np.nan
df.loc[df['last_tidal_volume_set'] < 200, 'last_tidal_volume_set'] = np.nan

df.loc[df['last_plateau_pressure'] > 45, 'last_plateau_pressure'] = np.nan
df.loc[df['last_plateau_pressure_change'].abs() > 10, 'last_plateau_pressure_change'] = np.nan

condition = (np.log(df['last_peak_insp_pressure']) > 4) | (np.log(df['last_peak_insp_pressure']) < 1)
df.loc[condition, 'last_peak_insp_pressure'] = np.nan

df.loc[df['last_mean_airway_pressure'] > 50, 'last_mean_airway_pressure'] = np.nan
df.loc[df['last_inspiratory_time'] > 1.5, 'last_inspiratory_time'] = np.nan
df.loc[df['last_dp_change_since_prev_dp_meas'].abs() > 10, 'last_driving_pressure'] = np.nan
df.loc[df['last_dp_change_since_prev_dp_meas'].abs() > 10, 'last_dp_change_since_prev_dp_meas'] = np.nan
df['last_pao2fio2ratio'] = np.minimum(df['last_pao2fio2ratio'], 600)

# TODO: Add an extra row when control = 1 at time before exiting hospital
