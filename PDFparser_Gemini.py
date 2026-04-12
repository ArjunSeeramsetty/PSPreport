import tabula
import pandas as pd
import os
from PyPDF2 import PdfReader
from datetime import datetime
import re
import logging
import warnings
from smart_table_classifier import SmartTableClassifier, TableClassification

# Suppress specific warnings
warnings.filterwarnings("ignore", category=FutureWarning, module="tabula")
warnings.filterwarnings("ignore", message=".*restricted method.*")
warnings.filterwarnings("ignore", message=".*java.lang.System.*")

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Full PSPTransformer class (insert your actual logic for each method) ---
class PSPTransformer:
    def __init__(self, report_date):
        self.report_date = report_date
        self.logger = logging.getLogger(self.__class__.__name__)

    def _clean_column_names(self, df_columns):
        cleaned_cols = []
        for col in df_columns:
            cleaned_col = str(col).strip().replace('\n', ' ', -1)
            cleaned_col = cleaned_col.replace('*', '', -1).replace('(', '', -1).replace(')', '', -1)
            cleaned_cols.append(cleaned_col)
        return cleaned_cols

    def _add_common_cols(self, df, table_name):
        df_out = df.copy()
        df_out['Date'] = self.report_date
        df_out['Table Name'] = table_name # Corrected from 'Excchange' if it was specific to one call
        return df_out

    def transform_states(self, raw_df):
        df = raw_df.copy()
        target_csv_columns = [
            'Region', 'States', 'Maximum Demand (MW)', 'Shortage (MW)', 'Energy Met (MU)',
            'Drawal Schedule (MU)', 'OD(+)/UD(-) (MU)', 'Max OD (MW)', 'Energy Shortage (MU)'
        ]

        if df.shape[1] != len(target_csv_columns):
            raise ValueError(
                f"Error (States Table): Column count mismatch. "
                f"Expected {len(target_csv_columns)}, got {df.shape[1]}."
            )
        df.columns = target_csv_columns

        # Convert numeric columns to float64 at the start
        numeric_cols = [
            'Maximum Demand (MW)', 'Shortage (MW)', 'Energy Met (MU)',
            'Drawal Schedule (MU)', 'OD(+)/UD(-) (MU)', 'Max OD (MW)', 'Energy Shortage (MU)'
        ]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').astype('float64')

        if 'Region' in df.columns:
            region_codes = ['NR', 'WR', 'SR', 'ER', 'NER', 'ALL INDIA']
            mask = (~df['Region'].isin(region_codes)) & (df['Region'].notna())
            idx = df.index[mask]
            
            for i in idx:
                # Get the row and shift it
                row = df.iloc[i].copy()
                shifted_values = row.shift(1, fill_value=pd.NA)
                
                # Assign values back maintaining dtypes
                for col in df.columns:
                    if col in numeric_cols:
                        # For numeric columns, ensure float64
                        df.at[i, col] = pd.to_numeric(shifted_values[col], errors='coerce')
                    else:
                        # For non-numeric columns (Region, States), keep as is
                        df.at[i, col] = shifted_values[col]

        region_mapping = {
            'Punjab': 'NR', 'Haryana': 'NR', 'Rajasthan': 'NR', 'Delhi': 'NR', 'UP': 'NR',
            'Uttarakhand': 'NR', 'HP': 'NR', 'J&K(UT) & Ladakh(UT)': 'NR', 'J&K(UT) &.': 'NR', 'Chandigarh': 'NR', 'Railways_NR ISTS': 'NR',
            'RailwaysNR ISTS': 'NR', 'Railways_NR': 'NR',
            'Chhattisgarh': 'WR', 'Gujarat': 'WR', 'MP': 'WR', 'Maharashtra': 'WR', 'Goa': 'WR',
            'DNHDDPDCL': 'WR', 'AMNSIL': 'WR', 'BALCO': 'WR', 'RIL JAMNAGAR': 'WR',
            'Andhra Pradesh': 'SR', 'Telangana': 'SR', 'Karnataka': 'SR', 'Kerala': 'SR', 'Tamil Nadu': 'SR', 'Puducherry': 'SR',
            'Bihar': 'ER', 'DVC': 'ER', 'Jharkhand': 'ER', 'Odisha': 'ER', 'West Bengal': 'ER', 'Sikkim': 'ER', 'Railways_ER ISTS': 'ER', 'RailwaysER ISTS': 'ER', 'Railways_ER': 'ER',
            'Arunachal Pradesh': 'NER', 'Arunachal': 'NER', 'Assam': 'NER', 'Manipur': 'NER', 'Meghalaya': 'NER', 'Mizoram': 'NER', 'Nagaland': 'NER', 'Tripura': 'NER',
            # Add missing state mappings
            'J&K(UT) &': 'NR',
            'J&K(UT)': 'NR',
            'JAMMU & KASHMIR (UT)': 'NR',
            'Railways_NR': 'NR',
            'Railways_ER': 'ER'
        }
        
        if 'States' in df.columns and 'Region' in df.columns:
            # Handle state mapping...
            unmapped_states = []
            for state in df['States'].dropna().astype(str).str.strip().unique():
                if state and state not in region_mapping:
                    # Ignore region codes that appear in States column
                    if state in ['ER', 'WR', 'SR', 'NR', 'NER']:
                        continue
                    if not any(summary_keyword in state.upper() for summary_keyword in ["TOTAL", "ALL INDIA"]):
                        unmapped_states.append(state)
            
            if unmapped_states:
                raise ValueError(
                    f"Error (States Table): Unmapped states found: {', '.join(unmapped_states)}."
                )

            df['Region'] = df.apply(lambda row: region_mapping.get(str(row['States']).strip(), row['Region']), axis=1)
            df['Region'] = df['Region'].replace('', pd.NA).ffill()
        else:
            raise ValueError("Error (States Table): 'States' or 'Region' column not found for mapping.")

        # Clean and convert numeric columns one final time
        for col in numeric_cols:
            if col in df.columns:
                # Remove commas and clean up decimal points
                df[col] = df[col].astype(str).str.replace(',', '', regex=False).str.strip()
                df[col] = df[col].str.replace(r'\.+', '.', regex=True).str.rstrip('.')
                # Convert to float64
                df[col] = pd.to_numeric(df[col], errors='coerce').astype('float64')

        df = self._add_common_cols(df, 'States')
        final_ordered_columns = ['Date', 'Table Name'] + target_csv_columns
        return df[final_ordered_columns]

    def transform_international_net(self, raw_df):
        df = raw_df.copy()

        # Correction: Raw table from tabula should have 2 rows and 5 columns.
        expected_rows, expected_cols_raw = 2, 5
        if not (df.shape[0] == expected_rows and df.shape[1] == expected_cols_raw):
            raise ValueError(
                f"Error (International NET): Raw table shape mismatch. "
                f"Expected ({expected_rows} rows, {expected_cols_raw} cols), got {df.shape}. "
                f"Check PDF structure or tabula extraction."
            )
        
        # Values from 2nd to 5th column (index 1 to 4) for both rows
        numeric_list = df.iloc[0, 1:expected_cols_raw].tolist() + df.iloc[1, 1:expected_cols_raw].tolist()

        target_columns = [ # 8 target columns
            'Bhutan (MU)', 'Nepal (MU)', 'Bangladesh (MU)', 'Godda (Bangladesh) (MU)', 
            'Bhutan Peak (MW)', 'Nepal Peak (MW)', 'Bangladesh Peak (MW)', 'Godda (Bangladesh) Peak (MW)'
        ]
        
        if len(numeric_list) != len(target_columns):
            # This should not happen if raw table shape is (2,5) and numeric_list extraction is correct (4+4=8)
            raise ValueError(
                f"Error (International NET): Mismatch between extracted values ({len(numeric_list)}) "
                f"and target columns ({len(target_columns)}). Logic error in numeric_list creation."
            )
        
        df_processed = pd.DataFrame([numeric_list], columns=target_columns)
        
        for col in target_columns:
            df_processed[col] = pd.to_numeric(df_processed[col], errors='coerce')
        
        df_processed = self._add_common_cols(df_processed, 'International NET')
        
        final_ordered_columns = ['Date', 'Table Name'] + target_columns
        # Correction: Final processed table must have all columns as in final_ordered_columns.
        if not all(col in df_processed.columns for col in final_ordered_columns) or \
           len(df_processed.columns) != len(final_ordered_columns):
            # This check is somewhat redundant if df_processed is built correctly above.
            raise ValueError(
                f"Error (International NET): Final processed table columns mismatch. "
                f"Expected {len(final_ordered_columns)} columns: {final_ordered_columns}, "
                f"Got {len(df_processed.columns)} columns: {df_processed.columns.tolist()}."
            )
        return df_processed[final_ordered_columns]


    def transform_regional_summary(self, raw_df_A, raw_df_B, raw_df_E, raw_df_F, raw_df_G_main, raw_df_G_share, raw_df_H, raw_df_I):
        melted_data_list = []
        
        # --- Pre-process G_Main to get its cleaned column structure for G_Share ---
        df_g_main_for_cols = raw_df_G_main.copy()
        if df_g_main_for_cols.empty:
            raise ValueError("Error (Regional Summary - G_Main for G_Share): raw_df_G_main is empty, cannot proceed.")
        
        # Assuming G_Main's first row (if multi-row header) or its columns (if single/no header) are relevant
        # For simplicity, let's assume tabula's output columns for G_Main are somewhat usable or need cleaning.
        # This relies on _clean_column_names being robust for G_Main's header structure.
        # A more robust dynamic header finding for G_Main would be ideal here.
        # For now, clean whatever columns raw_df_G_main has.
        cleaned_g_main_cols = self._clean_column_names(df_g_main_for_cols.columns)


        # --- Process G_Share using G_Main's column structure (Correction) ---
        df_g_share_copy = raw_df_G_share.copy()
        if df_g_share_copy.empty:
            raise ValueError("Error (Regional Summary - G_Share): raw_df_g_share is empty.")

        original_g_share_header_as_data = df_g_share_copy.columns.tolist()
        df_g_share_transformed = pd.DataFrame([original_g_share_header_as_data], columns=cleaned_g_main_cols[:len(original_g_share_header_as_data)])
        if df_g_share_copy.shape[0] > 0 :
            g_share_data_df = pd.DataFrame(data=df_g_share_copy.values, columns=cleaned_g_main_cols[:df_g_share_copy.shape[1]])
            df_g_share_transformed = pd.concat([df_g_share_transformed, g_share_data_df], ignore_index=True)
        if df_g_share_transformed.shape[1] >= 2:
            g_share_metrics_col = df_g_share_transformed.columns[0]
            g_share_region_cols = df_g_share_transformed.columns[1:]
            df_g_share_melted = df_g_share_transformed.melt(
                id_vars=[g_share_metrics_col], value_vars=g_share_region_cols,
                var_name='Region', value_name='Value'
            )
            df_g_share_melted.rename(columns={g_share_metrics_col: 'Metric'}, inplace=True)
            df_g_share_melted['Region'] = df_g_share_melted['Region'].astype(str).str.strip().replace(
                {'TOTAL': 'India', 'All India': 'India', '% Share': 'India'}, regex=False
            )
            df_g_share_melted['MetricSource'] = 'G_Share'
            melted_data_list.append(df_g_share_melted[['Metric', 'Region', 'Value', 'MetricSource']])
        else:
            raise ValueError("Error (Regional Summary - G_Share): Transformed G_Share table is not wide enough to melt after column assignment.")

        # --- Process Tables A, E, F, G_main (G_main is processed again for its own data) ---
        data_sources_for_melt = [
            (raw_df_A, 'A'), (raw_df_E, 'E'), (raw_df_F, 'F'), (raw_df_G_main, 'G_Main')
        ]
        for df_source, source_name in data_sources_for_melt:
            df_temp = df_source.copy()
            if df_temp.empty or df_temp.shape[1] < 2:
                raise ValueError(f"Error (Regional Summary - {source_name}): Source table is empty or has < 2 columns.")
            
            df_temp.columns = self._clean_column_names(df_temp.columns) # Clean columns before melt
            metrics_col_name = df_temp.columns[0]
            region_col_names = df_temp.columns[1:]
            # Add a source column to preserve origin
            df_temp['MetricSource'] = source_name
            df_melted = df_temp.melt(
                id_vars=[metrics_col_name, 'MetricSource'], value_vars=region_col_names,
                var_name='Region', value_name='Value'
            )
            df_melted.rename(columns={metrics_col_name: 'Metric'}, inplace=True)
            df_melted['Region'] = df_melted['Region'].astype(str).str.strip().replace(
                {'TOTAL': 'India', 'All India': 'India', '% Share': 'India'}, regex=False
            )
            melted_data_list.append(df_melted[['Metric', 'Region', 'Value', 'MetricSource']])

        combined_melted_df = pd.concat(melted_data_list, ignore_index=True)

        # --- Process Table B: Frequency Profile (%) ---
        df_b = raw_df_B.copy()
        if df_b.empty:
            raise ValueError("Error (Regional Summary - B): Frequency Profile table is empty.")

        all_india_mask = df_b.iloc[:, 0].astype(str).str.contains('All India', case=False, na=False)
        if not any(all_india_mask):
            raise ValueError("Error (Regional Summary - B): Could not find 'All India' row in Frequency Profile table.")

        all_india_row = df_b[all_india_mask].iloc[0]
        freq_metrics = [
            ('FVI', 1),
            ('Frequency (<49.7)', 2),
            ('Frequency (49.7 - 49.8)', 3),
            ('Frequency (49.8 - 49.9)', 4),
            ('Frequency (< 49.9)', 5),
            ('Frequency (49.9 - 50.05)', 6),
            ('Frequency (> 50.05)', 7)
        ]
        for metric_name, col_idx in freq_metrics:
            if col_idx < len(all_india_row):
                value = all_india_row.iloc[col_idx]
                try:
                    value = pd.to_numeric(str(value).replace('%', '').strip(), errors='coerce')
                except:
                    value = None
                combined_melted_df.loc[len(combined_melted_df)] = {
                    'Metric': metric_name,
                    'Region': 'India',
                    'Value': value,
                    'MetricSource': 'B'
                }

        # --- Process Table H: All India Demand Diversity Factor (Correction) ---
        df_h_copy = raw_df_H.copy()
        if not (df_h_copy.shape[0] == 1 and df_h_copy.shape[1] == 2):
            raise ValueError(
                f"Error (Regional Summary - H): Table H shape mismatch. "
                f"Expected (1 row of data, 2 columns), got {df_h_copy.shape}. "
                f"Tabula output: columns={df_h_copy.columns.tolist()}, first data row={df_h_copy.iloc[0].tolist() if df_h_copy.shape[0]>=1 else 'N/A'}"
            )
        combined_melted_df.loc[len(combined_melted_df)] = {
            'Metric': 'Region DDF', 'Region': 'India', 'Value': str(df_h_copy.columns[1]), 'MetricSource': 'H'
        }
        combined_melted_df.loc[len(combined_melted_df)] = {
            'Metric': 'States DDF', 'Region': 'India', 'Value': df_h_copy.iloc[0, 1], 'MetricSource': 'H'
        }

        # --- Process Table I: All India Peak Demand and shortage ---
        df_i_copy = raw_df_I
        expected_rows, expected_cols_raw = 2, 4
        table_i_metrics = [
            'SolarHR Max Demand', 'SolarHR Max Demand Time', 'SolarHR Shortage',
            'Non-SolarHR Max Demand', 'Non-SolarHR Max Demand Time', 'Non-SolarHR Shortage'
        ]
        table_i_values = [None] * len(table_i_metrics)
        if df_i_copy is not None and df_i_copy.shape == (expected_rows, expected_cols_raw):
            try:
                numeric_list = df_i_copy.iloc[0, 1:expected_cols_raw].tolist() + df_i_copy.iloc[1, 1:expected_cols_raw].tolist()
                if len(numeric_list) == len(table_i_metrics):
                    table_i_values = numeric_list
            except Exception:
                pass
        # Always add Table I metrics, fill with None if missing/malformed
        for idx, metric_name in enumerate(table_i_metrics):
            combined_melted_df.loc[len(combined_melted_df)] = {
                'Metric': metric_name,
                'Region': 'India',
                'Value': table_i_values[idx],
                'MetricSource': 'I'
            }

        if combined_melted_df.empty:
            raise ValueError("Error (Regional Summary): No data to pivot after processing all sources.")
        
        # Combine MetricSource and Metric for unique metric names
        combined_melted_df['MetricFull'] = combined_melted_df['MetricSource'] + '_' + combined_melted_df['Metric']

        pivoted_dfs_list = []
        for region_name in combined_melted_df['Region'].unique():
            df_region_specific = combined_melted_df[combined_melted_df['Region'] == region_name]
            df_pivoted = df_region_specific.pivot_table(
                index='Region', columns='MetricFull', values='Value', aggfunc='first'
            ).reset_index()
            df_pivoted['Table Name'] = 'Regional Summary'  # Set to 'Regional Summary' instead of region name
            df_pivoted['Date'] = self.report_date
            # Order columns: Date, Table Name, then all metrics
            ordered_columns = ['Date', 'Table Name'] + [col for col in df_pivoted.columns if col not in ['Date', 'Table Name']]
            df_pivoted = df_pivoted.reindex(columns=ordered_columns)
            pivoted_dfs_list.append(df_pivoted)

        if not pivoted_dfs_list:
             raise ValueError("Error (Regional Summary): Pivoting resulted in no DataFrames.")
        final_output_df = pd.concat(pivoted_dfs_list, ignore_index=True)

        # Convert all columns except 'Date' and 'Table Name' to numeric where possible
        for col in final_output_df.columns:
            if col not in ['Date', 'Table Name']:
                final_output_df[col] = pd.to_numeric(final_output_df[col], errors='ignore')

        return final_output_df


    def transform_inter_region(self, raw_df_orig):
        # Do NOT drop the first column yet
        df = raw_df_orig.copy()  # Keep all columns
        processed_rows_data = []
        for i in range(df.shape[0]):
            try:
                row_series = df.iloc[i]
                row_values = row_series.tolist()
                non_na_values = [v for v in row_values if pd.notna(v) and str(v).strip() != ""]
                current_row_values = [pd.NA] * 10  # 1 extra for serial number
                if len(non_na_values) == 4:
                    import_value = str(non_na_values[0]).strip()
                    for j in range(3):
                        current_row_values[6 + j] = non_na_values[1 + j]  # shift by 1 for serial number
                    current_row_values[9] = import_value  # Import column at the end
                    current_row_values[2] = 'Total'
                else:
                    for idx in range(min(9, len(row_values))):
                        current_row_values[idx] = row_values[idx]
                    current_row_values[9] = pd.NA
                processed_rows_data.append(current_row_values)
            except Exception as e:
                self.logger.error(f"Error processing row {i}: {str(e)}")
                continue
        # Now drop the serial number column (index 0) before assigning column names
        df_processed = pd.DataFrame(processed_rows_data)
        df_processed = df_processed.iloc[:, 1:]  # Drop serial number
        target_csv_cols = ['Voltage Level', 'Line Details', 'No. of Circuit', 
                          'Max Import (MW)', 'Max Export (MW)', 'Import (MU)', 
                      'Export (MU)', 'NET Import (MU)', 'Import']
        df_processed.columns = target_csv_cols
        # Backfill the Import column with the last known import region header
        df_processed['Import'] = df_processed['Import'].bfill()
        df_processed = df_processed.dropna(thresh=max(1, len(target_csv_cols) - 5))
        numeric_cols = ['No. of Circuit', 'Max Import (MW)', 'Max Export (MW)', 
                       'Import (MU)', 'Export (MU)', 'NET Import (MU)']
        for col in numeric_cols:
            if col in df_processed.columns:
                df_processed[col] = pd.to_numeric(df_processed[col], errors='coerce')
        df_processed = self._add_common_cols(df_processed, 'Inter-Region')
        final_ordered_columns = ['Date', 'Table Name', 'Import'] + \
                              [col for col in target_csv_cols if col != 'Import']
        # Correction: Ensure final table has columns exactly as in final_ordered_columns
        if not all(col in df_processed.columns for col in final_ordered_columns) or \
           len(df_processed.columns) != len(final_ordered_columns):
            missing_cols = [col for col in final_ordered_columns if col not in df_processed.columns]
            extra_cols = [col for col in df_processed.columns if col not in final_ordered_columns]
            raise ValueError(
                f"Error (Inter-Region): Final column structure mismatch. "
                f"Expected: {final_ordered_columns}. Got: {df_processed.columns.tolist()}. "
                f"Missing: {missing_cols}, Extra: {extra_cols}."
            )
        return df_processed[final_ordered_columns]

    def transform_international_exchange(self, raw_df):
        df = raw_df.copy()
        if df.empty:
            # raise ValueError("Error (International Exchange): Raw table is empty.")
            print("Warning (International Exchange): Raw table is empty. Returning empty DataFrame.")
            return self._add_common_cols(pd.DataFrame(), 'International')


        # Assumes header is in the first row of tabula's output
        df_header = self._clean_column_names(df.iloc[0])
        df_data = df.iloc[1:].copy() # Make a copy for modification
        df_data.columns = df_header # Assign cleaned header to the rest of the data
        df = df_data.reset_index(drop=True)

        target_cols_final = ['State', 'Region', 'Line Name', 'Max (MW)', 
                             'Min (MW)', 'Avg (MW)', 'Energy Exchange (MU)']

        # Correction: Direct column assignment if count matches, else error.
        if df.shape[1] != len(target_cols_final):
            raise ValueError(
                f"Error (International Exchange): Column count mismatch after header assignment. "
                f"Expected {len(target_cols_final)} based on target, got {df.shape[1]} from data ({df.columns.tolist()})."
            )
        df.columns = target_cols_final # Assign target names, assuming order is correct

        if 'State' in df.columns: # Now 'State' is a target column name
            idx_to_shift = df.index[df['State'].astype(str).str.contains('ER', na=False)]
            for i in idx_to_shift:
                df.iloc[i,:] = df.iloc[i,:].astype(str).shift(1, fill_value=pd.NA)
            df['State'] = df['State'].replace('', pd.NA).ffill()
            if 'Region' in df.columns:
                df['Region'] = df['Region'].replace('', pd.NA).ffill()
        
        if 'State' in df.columns:
             df = df[~df['State'].astype(str).str.contains('Total', na=False, case=False)].copy()
        
        numeric_cols = ['Max (MW)', 'Min (MW)', 'Avg (MW)', 'Energy Exchange (MU)']
        for col in numeric_cols:
            if col in df.columns: # Should exist due to direct assignment
                df[col] = pd.to_numeric(df[col], errors='coerce')

        df = self._add_common_cols(df, 'International')
        final_ordered_columns = ['Date', 'Table Name'] + target_cols_final
        # Final check already implicitly handled by df.columns = target_cols_final if counts match
        return df[final_ordered_columns]


    def transform_exchange(self, raw_df_export, raw_df_import, raw_df_net):
        all_exchange_dfs = []

        def process_single_exchange_table(df_raw_single, exchange_type):
            df_single_processed = df_raw_single.copy()
            if df_single_processed.shape[0] <= 3: # Need more than 3 rows to skip 3
                 print(f"Warning (Exchange - {exchange_type}): Not enough rows (<=3) to process. Skipping.")
                 return pd.DataFrame()
            
            df_single_processed = df_single_processed.iloc[3:, :].reset_index(drop=True)
            if df_single_processed.empty: # check if empty after slicing
                print(f"Warning (Exchange - {exchange_type}): Became empty after skipping first 3 rows. Skipping.")
                return pd.DataFrame()

            raw_cols_exchange = ['Country', 'PPA', 'Bilateral', 'DAM IEX', 'DAM PXIL', 
                                 'DAM HPX', 'RTM IEX', 'RTM PXIL', 'RTM HPX', 'Total']
            
            if df_single_processed.shape[1] != len(raw_cols_exchange):
                raise ValueError(
                    f"Error (Exchange - {exchange_type}): Column count mismatch. "
                    f"Expected {len(raw_cols_exchange)}, got {df_single_processed.shape[1]}."
                )
            df_single_processed.columns = raw_cols_exchange

            # Correction: Do NOT filter out "Total" in 'Country' column.
            # df_single_processed = df_single_processed[~df_single_processed['Country'].astype(str).str.contains('Total', na=False, case=False)].copy()

            df_single_processed['Type'] = exchange_type
             # Correction: Use 'Exchange' not 'Excchange'
            df_single_processed = self._add_common_cols(df_single_processed, 'Exchange')
            
            expected_cols_sub_table = ['Date', 'Table Name', 'Type'] + raw_cols_exchange
            # Ensure all columns are present (should be, due to assignment and addition)
            for col in expected_cols_sub_table:
                if col not in df_single_processed.columns: # Should not happen
                    df_single_processed[col] = pd.NA 
            return df_single_processed[expected_cols_sub_table]

        # (Processing logic for each exchange type, appending to all_exchange_dfs)
        # ... (similar to previous, calling process_single_exchange_table)
        df_export = process_single_exchange_table(raw_df_export, 'Export')
        if not df_export.empty: all_exchange_dfs.append(df_export)
        df_import = process_single_exchange_table(raw_df_import, 'Import')
        if not df_import.empty: all_exchange_dfs.append(df_import)
        df_net = process_single_exchange_table(raw_df_net, 'NET')
        if not df_net.empty: all_exchange_dfs.append(df_net)


        if not all_exchange_dfs:
            # raise ValueError("Error (Exchange): All sub-tables (Export, Import, NET) resulted in empty DataFrames.")
            print("Warning (Exchange): All sub-tables (Export, Import, NET) were empty or malformed. Returning empty DataFrame.")
            return pd.DataFrame()


        combined_df = pd.concat(all_exchange_dfs, ignore_index=True)
        numeric_cols_exchange = ['PPA', 'Bilateral', 'DAM IEX', 'DAM PXIL', 'DAM HPX', 
                                 'RTM IEX', 'RTM PXIL', 'RTM HPX', 'Total']
        for col in numeric_cols_exchange:
            if col in combined_df.columns:
                combined_df[col] = pd.to_numeric(combined_df[col], errors='coerce')
        return combined_df


    def transform_block_wise(self, raw_df):
        df = raw_df.copy()
        header_row_start_idx = -1
        # (Header finding logic as before)
        for r_idx in range(min(df.shape[0], 5)):
            row_str = " ".join(df.iloc[r_idx].astype(str).fillna('').str.strip().tolist())
            if "TIME" in row_str and "FREQUENCY" in row_str and "DEMAND MET" in row_str:
                header_row_start_idx = r_idx
                break
        
        new_header_from_pdf = []
        if header_row_start_idx != -1:
            if header_row_start_idx + 1 < df.shape[0]:
                top_header_series = df.iloc[header_row_start_idx].astype(str).fillna('')
                bottom_header_series = df.iloc[header_row_start_idx + 1].astype(str).fillna('')
                temp_new_columns = []
                for i in range(len(top_header_series)):
                    top_part = top_header_series.iloc[i].strip()
                    bottom_part = bottom_header_series.iloc[i].strip() if i < len(bottom_header_series) else ''
                    combined_name = bottom_part
                    if top_part and top_part != bottom_part:
                        combined_name = f"{top_part} {bottom_part}".strip()
                    elif not bottom_part and top_part:
                        combined_name = top_part
                    temp_new_columns.append(combined_name)
                new_header_from_pdf = self._clean_column_names(temp_new_columns)
                df = df.iloc[header_row_start_idx + 2:].reset_index(drop=True)
            else:
                new_header_from_pdf = self._clean_column_names(df.iloc[header_row_start_idx])
                df = df.iloc[header_row_start_idx + 1:].reset_index(drop=True)
        else:
            if df.empty: raise ValueError("Error (Block-wise): Raw table is empty and no header found.")
            new_header_from_pdf = self._clean_column_names(df.iloc[0]) # Fallback
            df = df.iloc[1:].reset_index(drop=True)
        
        df.columns = new_header_from_pdf # Assign header derived from PDF

        # Flexible column mapping based on available columns
        standard_csv_names_map = { 
            'TIME': 'TIME',
            'FREQUENCY HZ': 'FREQUENCY (Hz)',
            'FREQUENCY': 'FREQUENCY (Hz)',
            'DEMAND MET MW': 'DEMAND MET (MW)',
            'DEMAND MET': 'DEMAND MET (MW)',
            'NUCLEAR MW': 'NUCLEAR (MW)',
            'NUCLEAR': 'NUCLEAR (MW)',
            'WIND MW': 'WIND (MW)',
            'WIND': 'WIND (MW)',
            'SOLAR MW': 'SOLAR (MW)',
            'SOLAR': 'SOLAR (MW)',
            'HYDRO MW': 'HYDRO (MW)',
            'HYDRO': 'HYDRO (MW)',
            'GAS MW': 'GAS (MW)',
            'GAS': 'GAS (MW)',
            'THERMAL MW': 'THERMAL (MW)',
            'THERMAL': 'THERMAL (MW)',
            'OTHERS MW': 'OTHERS* (MW)',
            'OTHERS': 'OTHERS* (MW)',
            'NET DEMAND MET MW': 'NET DEMAND MET (MW)',
            'NET DEMAND MET': 'NET DEMAND MET (MW)',
            'TOTAL GENERATION MW': 'TOTAL GENERATION (MW)',
            'TOTAL GENERATION': 'TOTAL GENERATION (MW)',
            'NET TRANSNATIONAL EXCHANGE MW +VE IMPORT -VE EXPORT': 'NET TRANSNATIONAL EXCHANGE (MW) (+ve) Import, (-ve) Export',
            'NET TRANSNATIONAL EXCHANGE': 'NET TRANSNATIONAL EXCHANGE (MW) (+ve) Import, (-ve) Export'
        }

        # Map available columns to standard names
        mapped_columns = []
        for col in df.columns:
            mapped_name = standard_csv_names_map.get(col, col)  # Keep original if not in mapping
            mapped_columns.append(mapped_name)
        
        df.columns = mapped_columns

        # Define all possible numeric columns
        all_numeric_cols = [
            'FREQUENCY (Hz)', 'DEMAND MET (MW)', 'NUCLEAR (MW)', 'WIND (MW)', 'SOLAR (MW)',
            'HYDRO (MW)', 'GAS (MW)', 'THERMAL (MW)', 'OTHERS* (MW)', 'NET DEMAND MET (MW)',
            'TOTAL GENERATION (MW)', 'NET TRANSNATIONAL EXCHANGE (MW) (+ve) Import, (-ve) Export'
        ]
        
        # Process only the numeric columns that exist in the dataframe
        for col in all_numeric_cols:
            if col in df.columns:
                df[col] = df[col].astype(str).str.replace(',', '', regex=False).str.strip()
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

        df = self._add_common_cols(df, 'Block-wise')
        
        # Create final column list with only existing columns
        final_cols = ['Date', 'Table Name']
        if 'TIME' in df.columns:
            final_cols.append('TIME')
        final_cols.extend([col for col in all_numeric_cols if col in df.columns])
        
        return df[final_cols]

class PDFParser:
    """
    Encapsulates the process of parsing a PDF report.
    1. Extracts raw tables using tabula.
    2. Identifies tables robustly based on tabula key mapping.
    3. Transforms tables into a clean, standard format.
    """
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)

    def _get_report_date_from_pdf(self, pdf_path: str) -> str:
        """Extracts the report date strictly from the 'Sub: Daily PSP Report for the date' line, with fallback to filename."""
        try:
            reader = PdfReader(pdf_path)
            first_page_text = reader.pages[0].extract_text()
            # Strictly match the 'Sub: Daily PSP Report for the date' line
            match = re.search(r"Sub: Daily PSP Report for the date\s*(\d{1,2})\s*\.(\d{2})\.(\d{4})", first_page_text)
            if match:
                day = int(match.group(1))
                month = int(match.group(2))
                year = int(match.group(3))
                return f"{month}/{day}/{year}"
            
            # Fallback: Extract date from PDF filename (e.g., '07.04.23_NLDC_PSP.pdf' -> '4/7/2023')
            import os
            filename = os.path.basename(pdf_path)
            filename_match = re.search(r"(\d{2})\.(\d{2})\.(\d{2})_NLDC_PSP", filename)
            if filename_match:
                day = int(filename_match.group(1))
                month = int(filename_match.group(2))
                year = 2000 + int(filename_match.group(3))  # Convert 2-digit year to 4-digit
                return f"{month}/{day}/{year}"
            
            self.logger.warning("Could not find report date in PDF or filename.")
            return "Unknown Date"
        except Exception as e:
            self.logger.error(f"Error extracting report date: {e}")
            return "Unknown Date"

    def _extract_raw_tables(self, pdf_path: str) -> tuple[dict, str]:
        """Extracts raw tables and the report date from the PDF."""
        try:
            reader = PdfReader(pdf_path)
            num_pages = len(reader.pages)
        except Exception as e:
            self.logger.error(f"Error reading PDF for page count: {e}")
            return {}, "Unknown Date"

        processed_tables = {}
        report_date = self._get_report_date_from_pdf(pdf_path)
        for page_num in range(1, num_pages + 1):
            try:
                tables_on_page = tabula.read_pdf(
                    pdf_path,
                    pages=page_num,
                    multiple_tables=True,
                    guess=True,
                    lattice=True,
                    stream=True,
                    silent=True
                )
                for table_idx, table_df in enumerate(tables_on_page):
                    if isinstance(table_df, pd.DataFrame):
                        processed_tables[f"page_{page_num}_table_{table_idx}"] = table_df
            except Exception as e:
                self.logger.error(f"Error processing page {page_num}: {e}")
        return processed_tables, report_date

    def _identify_tables(self, raw_tables_dict: dict) -> dict:
        """Identifies tables using smart classification and returns both identified and raw tables."""
        self.logger.info("Starting smart table identification...")
        
        # Initialize the smart table classifier
        classifier = SmartTableClassifier()
        identified_tables = {}
        raw_tables_by_category = {}
        
        # Process each table with smart classification
        for tabula_key, df in raw_tables_dict.items():
            if df.empty:
                self.logger.warning(f"Skipping empty table: {tabula_key}")
                continue
                
            # Use smart classification to identify the table
            classification = classifier.classify_table(df, tabula_key)
            
            self.logger.info(f"Table {tabula_key}: classified as '{classification.category}' "
                           f"(confidence: {classification.confidence:.1f}%)")
            
            # Store raw table by category for processing
            category = classification.category
            if category not in raw_tables_by_category:
                raw_tables_by_category[category] = []
            raw_tables_by_category[category].append({
                'key': tabula_key,
                'data': df,
                'confidence': classification.confidence,
                'classification': classification
            })
            
            # Only process tables with reasonable confidence for logical mapping
            if classification.confidence > 15:  # Lower threshold to capture more tables
                # Map smart classification categories to logical table names
                logical_name = self._map_category_to_logical_name(classification.category, df)
                
                if logical_name:
                    identified_tables[logical_name] = df
                    self.logger.info(f"Mapped {tabula_key} to {logical_name}")
                else:
                    self.logger.warning(f"No logical name mapping found for category: {classification.category}")
            else:
                self.logger.warning(f"Low confidence classification for {tabula_key}: {classification.confidence:.1f}%")
        
        self.logger.info(f"Smart table identification complete. Found {len(identified_tables)} identified tables.")
        self.logger.info(f"Raw tables by category: {list(raw_tables_by_category.keys())}")
        
        # Log the identified tables for debugging
        if identified_tables:
            self.logger.info("Identified tables:")
            for logical_name, df in identified_tables.items():
                self.logger.info(f"  - {logical_name}: {df.shape[0]} rows, {df.shape[1]} columns")
        else:
            self.logger.warning("No tables were identified with sufficient confidence")
        
        # Store raw tables by category for processing
        self.raw_tables_by_category = raw_tables_by_category
        
        return identified_tables
    
    def _map_category_to_logical_name(self, category: str, df: pd.DataFrame) -> str:
        """
        Maps smart classification categories to logical table names used by the transformer.
        """
        # Get column text for additional context
        columns = [str(col).lower() for col in df.columns]
        column_text = " ".join(columns)
        
        # Apply context-based refinements first
        if category == 'regional_summary':
            # Distinguish between different types of regional summary tables
            if any(keyword in column_text for keyword in ['diversity', 'ddf']):
                return 'H. All India Demand Diversity Factor'
            elif any(keyword in column_text for keyword in ['solar', 'non-solar', 'peak demand']):
                return 'I. All India Peak Demand and shortage at Solar and Non-Solar Hour'
            elif any(keyword in column_text for keyword in ['demand met', 'energy met', 'peak demand']):
                return 'A. Power Supply Position at All India and Regional level'
            else:
                return 'A. Power Supply Position at All India and Regional level'
        
        elif category == 'transmission_flow':
            # Distinguish between different transmission/exchange tables
            if any(keyword in column_text for keyword in ['export from india']):
                return 'Export From India (in MU)'
            elif any(keyword in column_text for keyword in ['import by india']):
                return 'Import by India(in MU)'
            elif any(keyword in column_text for keyword in ['net from india']):
                return 'Net from India(in MU)'
            elif any(keyword in column_text for keyword in ['intra-national', 'inter-region']):
                return 'Intra-national Exchange'
            else:
                return 'E. Import/Export by Regions (in MU) - Import(+ve)/Export(-ve); OD(+)/UD(-)'
        
        elif category == 'international_exchange':
            # Distinguish between different international exchange tables
            if any(keyword in column_text for keyword in ['transnational', 'bhutan', 'nepal', 'bangladesh']):
                return 'D. Transnational Exchanges (MU) - Import(+ve)/Export(-ve)'
            else:
                return 'International Exchange'
        
        # Base category mapping for other categories
        category_mapping = {
            'frequency_profile': 'B. Frequency Profile (%)',
            'state_energy': 'C. Power Supply Position in States',
            'outage_data': 'F. Generation Outage(MW)',
            'generation_breakdown': 'G. Sourcewise generation (Gross) (MU)',
            're_share': 'G. Share of RE and Non-fossil',
            'time_block': '15 Min (INSTANTANEOUS) ALL INDIA GRID FREQUENCY, GENERATION & DEMAND MET (SCADA DATA)',
            'line_congestion': 'Line Congestion Data',
            'transnational_exchange': 'D. Transnational Exchanges (MU) - Import(+ve)/Export(-ve)'
        }
        
        return category_mapping.get(category, None)

    def process_pdf(self, pdf_path: str) -> list[pd.DataFrame]:
        """Main public method to orchestrate the full parsing of a PDF file."""
        self.logger.info(f"--- Starting PDF Parsing for: {pdf_path} ---")
        try:
            raw_tables, report_date = self._extract_raw_tables(pdf_path)
            if not raw_tables or report_date == "Unknown Date":
                self.logger.error("Failed to extract raw tables or report date from PDF.")
                return []
            
            # Get both identified tables and raw tables by category
            identified_tables = self._identify_tables(raw_tables)
            raw_tables_by_category = getattr(self, 'raw_tables_by_category', {})
            
            transformer = PSPTransformer(report_date)
            final_dataframes = []

            # Process regional summary with all available tables
            if 'regional_summary' in raw_tables_by_category:
                self.logger.info("Processing regional summary tables...")
                regional_tables = raw_tables_by_category['regional_summary']
                
                # Find the main regional summary table (highest confidence)
                main_regional_table = max(regional_tables, key=lambda x: x['confidence'])
                
                # Get supporting tables from other categories
                supporting_tables = {}
                
                # Frequency profile - include in regional summary
                if 'frequency_profile' in raw_tables_by_category:
                    freq_tables = raw_tables_by_category['frequency_profile']
                    supporting_tables['frequency'] = max(freq_tables, key=lambda x: x['confidence'])['data']
                
                # Transmission flow
                if 'transmission_flow' in raw_tables_by_category:
                    trans_tables = raw_tables_by_category['transmission_flow']
                    supporting_tables['transmission'] = max(trans_tables, key=lambda x: x['confidence'])['data']
                
                # Generation breakdown
                if 'generation_breakdown' in raw_tables_by_category:
                    gen_tables = raw_tables_by_category['generation_breakdown']
                    supporting_tables['generation'] = max(gen_tables, key=lambda x: x['confidence'])['data']
                
                # RE Share
                if 're_share' in raw_tables_by_category:
                    re_tables = raw_tables_by_category['re_share']
                    supporting_tables['re_share'] = max(re_tables, key=lambda x: x['confidence'])['data']
                
                # Outage data
                if 'outage_data' in raw_tables_by_category:
                    outage_tables = raw_tables_by_category['outage_data']
                    supporting_tables['outage'] = max(outage_tables, key=lambda x: x['confidence'])['data']
                
                # Demand diversity factor
                if 'demand_diversity_factor_ddf' in raw_tables_by_category:
                    ddf_tables = raw_tables_by_category['demand_diversity_factor_ddf']
                    supporting_tables['ddf'] = max(ddf_tables, key=lambda x: x['confidence'])['data']
                
                # Solar/non-solar hour
                if 'solar_nonsolar_hour' in raw_tables_by_category:
                    solar_tables = raw_tables_by_category['solar_nonsolar_hour']
                    supporting_tables['solar_nonsolar'] = max(solar_tables, key=lambda x: x['confidence'])['data']
                
                try:
                    # Process regional summary as a comprehensive table including frequency profile
                    df_regional = main_regional_table['data'].copy()
                    if not df_regional.empty:
                        # Add common columns
                        df_regional['Date'] = report_date
                        df_regional['Table Name'] = 'Regional Summary'
                        
                        # Clean and process the data
                        df_regional = df_regional.fillna('')
                        
                        # Convert to long format for easier processing
                        if df_regional.shape[1] > 2:
                            # Melt the dataframe to long format
                            id_cols = [df_regional.columns[0]]  # First column as identifier
                            value_cols = df_regional.columns[1:-2]  # Exclude Date and Table Name
                            
                            df_melted = df_regional.melt(
                                id_vars=id_cols,
                                value_vars=value_cols,
                                var_name='Region',
                                value_name='Value'
                            )
                            
                            # Rename the first column to Metric
                            df_melted = df_melted.rename(columns={id_cols[0]: 'Metric'})
                            
                            # Clean up the data
                            df_melted['Metric'] = df_melted['Metric'].astype(str).str.strip()
                            df_melted['Region'] = df_melted['Region'].astype(str).str.strip()
                            df_melted['Value'] = pd.to_numeric(df_melted['Value'], errors='coerce')
                            
                            # Remove rows with empty metrics or regions
                            df_melted = df_melted[
                                (df_melted['Metric'] != '') & 
                                (df_melted['Region'] != '') & 
                                (df_melted['Metric'] != 'nan') & 
                                (df_melted['Region'] != 'nan')
                            ]
                            
                            # Add frequency profile data if available
                            if 'frequency' in supporting_tables:
                                freq_df = supporting_tables['frequency']
                                if not freq_df.empty:
                                    all_india_mask = freq_df.iloc[:, 0].astype(str).str.contains('All India', case=False, na=False)
                                    if any(all_india_mask):
                                        all_india_row = freq_df[all_india_mask].iloc[0]
                                        freq_metrics = [
                                            ('FVI', 1), ('Frequency (<49.7)', 2), ('Frequency (49.7 - 49.8)', 3),
                                            ('Frequency (49.8 - 49.9)', 4), ('Frequency (< 49.9)', 5),
                                            ('Frequency (49.9 - 50.05)', 6), ('Frequency (> 50.05)', 7)
                                        ]
                                        for metric_name, col_idx in freq_metrics:
                                            if col_idx < len(all_india_row):
                                                value = all_india_row.iloc[col_idx]
                                                try:
                                                    value = pd.to_numeric(str(value).replace('%', '').strip(), errors='coerce')
                                                except:
                                                    value = None
                                                if value is not None:
                                                    df_melted.loc[len(df_melted)] = {
                                                        'Metric': metric_name,
                                                        'Region': 'India',
                                                        'Value': value
                                                    }
                            
                            if not df_melted.empty:
                                final_dataframes.append(df_melted)
                                self.logger.info("Regional summary processed successfully with frequency profile")
                            else:
                                self.logger.warning("Regional summary processing resulted in empty dataframe")
                        else:
                            self.logger.warning("Regional summary table has insufficient columns for processing")
                except Exception as e:
                    self.logger.error(f"Error processing regional summary: {e}")
            
            # Process individual tables by category in specific order
            self.logger.info("Processing individual tables by category...")
            
            # 1. States data (Index 1)
            if 'state_energy' in raw_tables_by_category:
                for table_info in raw_tables_by_category['state_energy']:
                    try:
                        df = transformer.transform_states(table_info['data'])
                        final_dataframes.append(df)
                        self.logger.info(f"States table processed from {table_info['key']}")
                    except Exception as e:
                        self.logger.error(f"Error processing states table from {table_info['key']}: {e}")
            
            # 2. Transnational Exchange (Index 2)
            if 'transnational_exchange' in raw_tables_by_category:
                for table_info in raw_tables_by_category['transnational_exchange']:
                    try:
                        df = transformer.transform_international_net(table_info['data'])
                        final_dataframes.append(df)
                        self.logger.info(f"Transnational exchange processed from {table_info['key']}")
                    except Exception as e:
                        self.logger.error(f"Error processing transnational exchange from {table_info['key']}: {e}")
            
            # 3. Inter-Region Transmission Flow (Index 3)
            if 'transmission_flow' in raw_tables_by_category:
                for table_info in raw_tables_by_category['transmission_flow']:
                    try:
                        df = transformer.transform_inter_region(table_info['data'])
                        final_dataframes.append(df)
                        self.logger.info(f"Inter-region transmission flow processed from {table_info['key']}")
                    except Exception as e:
                        self.logger.error(f"Error processing transmission flow from {table_info['key']}: {e}")
            
            # 4. International Transmission Flow (Index 4)
            if 'international_exchange' in raw_tables_by_category:
                for table_info in raw_tables_by_category['international_exchange']:
                    try:
                        df = transformer.transform_international_exchange(table_info['data'])
                        final_dataframes.append(df)
                        self.logger.info(f"International transmission flow processed from {table_info['key']}")
                    except Exception as e:
                        self.logger.error(f"Error processing international exchange from {table_info['key']}: {e}")
            
            # 5. Cross Border Exchange (Index 5)
            cross_border_categories = ['cross_border_schedule_1', 'cross_border_schedule_2', 'cross_border_schedule_3']
            cross_border_tables = []
            
            for category in cross_border_categories:
                if category in raw_tables_by_category:
                    cross_border_tables.extend(raw_tables_by_category[category])
            
            if cross_border_tables:
                # Collect all cross border schedule tables
                export_tables = []
                import_tables = []
                net_tables = []
                
                for table_info in cross_border_tables:
                    # Determine table type based on content
                    table_text = " ".join([str(cell) for cell in table_info['data'].values.flatten() if pd.notna(cell)])
                    if 'export' in table_text.lower():
                        export_tables.append(table_info['data'])
                    elif 'import' in table_text.lower():
                        import_tables.append(table_info['data'])
                    else:
                        net_tables.append(table_info['data'])
                
                # Process exchange tables if we have the required combination
                if export_tables and import_tables and net_tables:
                    try:
                        df = transformer.transform_exchange(export_tables[0], import_tables[0], net_tables[0])
                        final_dataframes.append(df)
                        self.logger.info("Cross border exchange tables processed successfully")
                    except Exception as e:
                        self.logger.error(f"Error processing cross border exchange tables: {e}")
            
            # 6. Block-Wise data (Index 6) - Only process if duration expectations are met
            if 'time_block' in raw_tables_by_category:
                for table_info in raw_tables_by_category['time_block']:
                    try:
                        # Check if blockwise table meets duration expectations
                        df = table_info['data']
                        table_content = " ".join(df.astype(str).fillna('').values.flatten())
                        
                        # Duration validation: should have around 96 time blocks (24 hours * 4 blocks per hour)
                        # Allow flexibility: minimum 90 rows for a full day of 15-minute data
                        has_time_content = ('TIME' in table_content or 'FREQUENCY' in table_content or 
                                          'THERMAL' in table_content or 'HYDRO' in table_content)
                        has_sufficient_rows = df.shape[0] >= 90  # Should have around 96 time blocks
                        has_sufficient_columns = df.shape[1] >= 3  # Should have at least TIME, FREQUENCY, and one other column
                        
                        if has_time_content and has_sufficient_rows and has_sufficient_columns:
                            df_processed = transformer.transform_block_wise(df)
                            final_dataframes.append(df_processed)
                            self.logger.info(f"Block-wise data processed from {table_info['key']} (rows: {df.shape[0]}, columns: {df.shape[1]})")
                        else:
                            self.logger.warning(f"Skipping blockwise table from {table_info['key']} - duration expectations not met: "
                                              f"time_content={has_time_content}, rows={df.shape[0]}>=90={has_sufficient_rows}, "
                                              f"columns={df.shape[1]}>=3={has_sufficient_columns}")
                    except Exception as e:
                        self.logger.error(f"Error processing time block from {table_info['key']}: {e}")

            if final_dataframes:
                self.logger.info("--- PDF Parsing Completed Successfully ---")
                self.logger.info(f"Processed {len(final_dataframes)} dataframes")
            else:
                self.logger.warning("--- PDF Parsing completed but no data extracted ---")
            return final_dataframes
        except Exception as e:
            self.logger.error(f"--- PDF Parsing Failed: {e} ---", exc_info=True)
            return []

# Example usage:
if __name__ == "__main__":
    parser_instance = PDFParser()
    dataframes_list = parser_instance.process_pdf("sample input/18.04.25_NLDC_PSP.pdf")
    # for df in dataframes_list:
    #     print(df.head())
    # Keep the console open
    import code
    code.interact(local=locals())