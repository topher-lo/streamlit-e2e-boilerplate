"""Individual data tasks (preprocessing, modelling, and postprocessing) are
encapsulated into the following functions:

--- Preprocessing ---

1. `retrieve_data`: retrieves data from a url, returns data
as a DataFrame

2. `_column_wrangler`: transforms column names
into a consistent format

3. `_obj_wrangler`: converts columns with
`object` dtype into `StringDtype`

4. `_factor_wrangler`:
converts columns in `is_cat` into `CategoricalDtype`

5. `_check_model_assumptions`: empty function

6. `clean_data`:
a pandas pipeline of data wranglers

7. `wrangle_na`:
wrangles missing values. 5 available strategies:
- Complete case
- Fill-in
- Fill-in with indicators
- Grand model
- MICE

8. `transform_data`: applies transformations on data

9. `encode_data`:
transforms columns with `category` dtype
using `pd.get_dummies`. NA values for each categorical column
are represented by their own dummy column.

--- Modelling ---

10. `run_model`: `statsmodels` linear regression implementation

--- Post-processing ---

11. `plot_confidence_intervals`: given a fitted OLS model in
`statsmodels`, returns a box and whisker regression coefficient plot.

Note 1. Public functions (i.e. functions without a leading underscore `_func`)
are wrapped around Prefect's `@task` decorator.

Note 2. Empty functions (e.g. `_check_model_assumptions`) are
suggested data tasks for the boilerplate's user to implement.
For instance, the model assumptions of multiple linear regression
(i.e. no multicollinearity) might not apply for another model
(e.g. non-parametric models such as random forest).

Note 3. The implementations in functions 9. and 10. are simple examples only.
Replace the code within these functions to according to your data model.
"""

import altair as alt
import datetime as dt
import numpy as np
import pandas as pd
import itertools

import statsmodels.api as sm

from patsy import dmatrix
from prefect import task
from typing import List
from typing import Union
from typing import Mapping
from .utils import clean_text

from sklearn.impute import SimpleImputer

from statsmodels.regression.linear_model import OLSResults
from statsmodels.imputation.mice import MICEData
from src.styles.altair import streamlit_theme
from pandas.api.types import is_categorical_dtype


# Pre-processing

@task(max_retries=3, retry_delay=dt.timedelta(seconds=10))
def retrieve_data(url: str,
                  sep: str = ',',
                  nrows: Union[None, int] = None) -> pd.DataFrame:
    """Reads data (from url string) into a DataFrame.
    Assumes download data is a text file (a.k.a flat file).
    `sep` defaults to ',' accept CSV files.

    If `sep` is specified as None, the separator is automatically
    detected using Python's builtin sniffer tool `csv.sniffer`.

    `nrows` specifies the number of rows of the file to read. Useful
    for examining the header without downloading the entire file, or
    for reading pieces of large files.

    Note 1. pandas uses its super fast C engine to read flat files
    ONLY IF `sep` is explicitly given. Otherwise, it uses
    Python's parsing engine to automically detect the seperator
    and read the file. The Python engine is considerably slower.

    Note 2. pandas's input/output API supports an extensive range of
    data formats. See https://pandas.pydata.org/pandas-docs/dev/user_guide/io.html
    for more information. Change the code within this function to retrieve data
    from sources other than CSV (e.g. data stored on a SQL database).

    Note 3. ignores unnamed index columns.
    """
    data = pd.read_csv(url, sep=sep)
    # Remove unnamed index columns
    data = data.loc[:, ~data.columns.str.contains('Unnamed')]
    return data


def _replace_na(
    data: pd.DataFrame,
    na_values: Union[None, List[Union[str, int, float]]]
) -> pd.DataFrame:
    """Replaces values in `na_values` with `np.nan`.
    """
    if na_values:
        data = data.replace(na_values, np.nan)
    return data


def _column_wrangler(data: pd.DataFrame) -> pd.DataFrame:
    """Returns DataFrame with columns transformed into a consistent format:
    1. Stripped of all whitespaces at start and end
    2. Any excess whitespace in between are replaced with an underscore "_"
    3. All characters are lowercased
    """
    data.columns = (data.columns
                        .str.strip()
                        .str.replace(r' +', '_')
                        .str.lower())
    return data


def _obj_wrangler(data: pd.DataFrame) -> pd.DataFrame:
    """Converts columns with `object` dtype to `StringDtype`.
    """
    obj_cols = (data.select_dtypes(include=['object'])
                    .columns)
    data.loc[:, obj_cols] = (data.loc[:, obj_cols]
                                 .astype('string'))
    return data


def _factor_wrangler(
    data: pd.DataFrame,
    is_cat: Union[None, List[str]],
    is_ordered: Union[None, List[str]],
    categories: Union[None, Mapping[str, List[Union[str, int, float]]]] = None,
    str_to_cat: bool = True,
    dummy_to_bool: bool = True,
) -> pd.DataFrame:
    """Converts columns in `is_cat` to `CategoricalDtype`.
    If `str_to_cat` is set to True, converts all `StringDtype` columns
    to `CategoricalDtype`.If `dummy_to_bool` is True, converts all columns
    with integer [0, 1] values into BooleanDtype.
    Sets columns in `is_ordered` to an orderer category. For keys
    (column names) in `categories`, sets respective column's categories
    to the key's corresponding value (list of str, int, or float).
    """

    cat_cols = []
    if str_to_cat:
        str_cols = (data.select_dtypes(include=['string'])
                        .columns
                        .tolist())
        cat_cols += str_cols
    if dummy_to_bool:
        # Select columns with [0, 1] values only
        dummy_cols = (data.loc[:, data.select_dtypes(include=['integer'])
                                      .apply(pd.Series.unique)
                                      .apply(sum) == 1])
        # Convert dummy_cols into BooleanDtype
        data.loc[:, dummy_cols] = data.loc[:, dummy_cols].astype('boolean')

    if is_cat:
        is_cat = [clean_text(col) for col in is_cat]  # Clean col names
        cat_cols += is_cat
    if cat_cols:
        for col in cat_cols:
            data.loc[:, col] = (data.loc[:, col]
                                    .astype('category'))
    # Set categories
    if categories:
        # Clean col names
        categories = {clean_text(k): v for k, v in categories.items()}
        for col, cats in categories.items():
            data.loc[:, col] = (data.loc[:, col]
                                    .cat
                                    .set_categories(cats))
    # Set is_ordered
    if is_ordered:
        is_ordered = [clean_text(col) for col in is_ordered]  # Clean col names
        for cat in is_ordered:
            data.loc[:, col] = (data.loc[:, col]
                                    .cat
                                    .as_ordered())
    return data


def _check_model_assumptions(data: pd.DataFrame) -> pd.DataFrame:
    """To be implemented. Write checks for your model's assumptions.
    Consider throwing a ValueError exception if critical assumptions
    are violated.
    """
    return data


@task
def clean_data(
    data: pd.DataFrame,
    na_values: Union[None, List[Union[str, int, float]]] = None,
    is_cat: Union[None, List[str]] = None,
    is_ordered: Union[None, List[str]] = None,
    categories: Union[None, Mapping[str, List[Union[str, int, float]]]] = None,
    str_to_cat: bool = True,
) -> pd.DataFrame:
    """Data preprocessing pipeline. Relaces values in `na_values`
    with `np.nan` and runs the following data wranglers on `data`:
    1. convert_dtypes
    2. _replace_na
    3. _column_wrangler
    4. _obj_wrangler
    5. _factor_wrangler
    6. _check_model_assumptions
    """
    data = (data.convert_dtypes()
                .pipe(_replace_na, na_values)
                .pipe(_column_wrangler)
                .pipe(_obj_wrangler)
                .pipe(_factor_wrangler,
                      is_cat,
                      is_ordered,
                      categories,
                      str_to_cat)
                .pipe(_check_model_assumptions))
    return data


@task
def wrangle_na(data: pd.DataFrame,
               method: str,
               cols: Union[None, List[str]] = None,
               **kwargs) -> pd.DataFrame:
    """Wrangles missing values in `data` according to the
    strategy specified in `method`.

    Available methods:
    1. Complete case (`cc`) -- drops all missing values.

    2. Fill-in (`fi`) -- imputes missing values with sklearn's `SimpleImputer`

    3. Fill-in with indicators (`fii`) --
    imputes missing values with sklearn's `SimpleImputer`; creates indicator
    columns for patterns of missing values across feature columns.

    4. Fill-in with indicators and interactions (AKA grand model) (`gm`) --
    imputes missing values with sklearn's `SimpleImputer`; creates indicator
    columns akin to strategy 3; creates additional missing value indictor
    columns for the complete set of interactions between features and the
    missing value indactors.

    5. Multiple imputation with chained equations (`mice`) --
    performs MICE procedure. Returns each imputed dataset from N draws of
    the original dataset. Optional arguments to specify in `kwargs`:
    - `n_burnin` --
    first `n_burnin` MICE iterations to skip; defaults to 20.
    - `n_imputations` --
    number of MICE iterations to save after burn-in phase; defaults to 10.
    - `n_spread` --
    number of MICE iterations to skip between saved imputations; defaults to 20.

    Note 1. `**kwargs` contains required or optional keyword arguments for
    `sklearn.preprocessing.SimpleImputer` and
    `statsmodels.imputation.mice.MICEData`.

    Note 2. By default for `fi`, `fii`, and `gm`, missing values in
    non-categorical columns are replaced by the mean along the column.
    Missing values in categorical columns are replaced by the most
    frequent value along the column.
    """

    # If no missing values
    if pd.notna(data).all().all():
        return data

    # If complete case
    if method == 'cc':
        data = data.dropna(**kwargs)

    # If fill-in with indicators or grand model
    if method in ['fii', 'gm']:
        # Create indicator columns for patterns of na
        na_indicators = (data.applymap(lambda x: '1' if pd.isna(x) else '0')
                             .agg(''.join, axis=1)
                             .pipe(pd.get_dummies)
                             .add_prefix('na_'))
        data = data.join(na_indicators)

    # If fill-in (or related)
    if method in ['fi',  'fii', 'gm']:
        # SimpleImputer (numeric columns)
        # If kwargs not specified
        if not(kwargs):
            # SimpleImputer (floats)
            float_kwargs = {'strategy': 'mean'}
            float_cols = data.select_dtypes(include=['float']).columns
            data.loc[:, float_cols] = (
                data.loc[:, float_cols].pipe(SimpleImputer(**float_kwargs)
                                             .fit_transform))
            # SimpleImputer (integer)
            int_kwargs = {'strategy': 'median'}
            int_cols = data.select_dtypes(include=['integer']).columns
            data.loc[:, int_cols] = (
                data.loc[:, int_cols].pipe(SimpleImputer(**int_kwargs)
                                           .fit_transform))
            # SimpleImputer (categorical and boolean columns)
            fact_kwargs = {'strategy': 'most_frequent'}
            fact_cols = (data.select_dtypes(include=['category', 'boolean'])
                             .columns)
            data.loc[:, fact_cols] = (
                data.loc[:, fact_cols].pipe(SimpleImputer(**fact_kwargs)
                                            .fit_transform))

        # If kwargs and cols specified
        elif kwargs and cols:
            data.loc[:, cols] = (data.loc[:, cols]
                                     .pipe(SimpleImputer(**kwargs)
                                           .fit_transform))
        # If kwargs specified
        else:
            data = data.pipe(SimpleImputer(**kwargs).fit_transform)

    # If grand model
    if method == 'gm':
        # Get interactions between features and na_indicators
        na_cols = [col for col in data.columns if col.startswith('na_')]
        feature_cols = [col for col in data.columns if col not in na_cols]
        # Convert to non-nullable dtypes
        temp_data = pd.DataFrame(data[feature_cols + na_cols]
                                 .to_numpy()).infer_objects()
        temp_data.columns = feature_cols + na_cols
        # Get interactions
        interaction_terms = list(itertools.product(feature_cols, na_cols))
        interaction_formula = ' + '.join(
            ['Q("{}"):Q("{}")'.format(*term) for term
             in interaction_terms]
        ) + '-1'
        interactions = dmatrix(interaction_formula,
                               temp_data,
                               return_type='dataframe')
        data = data.join(interactions)

    # If MICE
    if method == 'mice':
        # Label encode columns
        column_codes = pd.Categorical(data.columns)
        # Dictionary codes label
        col_code_map = dict(enumerate(column_codes.categories))
        # Rename columns to standardized terms for patsy
        data.columns = [f'col{c}' for c in column_codes.codes]
        imputer = MICEData(data, **kwargs)
        n_burnin = kwargs.get('n_burnin', 20)
        n_imputations = kwargs.get('n_imputations', 10)
        n_spread = kwargs.get('n_spread', 20)
        imputed_datasets = []
        # Draw n_burnin + n_imputations + n_imputations * n_spread
        # MICE iterations
        for i in range(n_imputations + 1):
            if i == 0:
                # Burn-in phase
                imputer.update_all(n_iter=n_burnin)
            else:
                # Imputation phase
                # Select final update after n_spread iterations
                imputer.update_all(n_iter=n_spread)
                imputed_datasets.append(imputer.data)
        data = pd.concat(imputed_datasets,
                         keys=list(range(n_imputations)))
        data.index = data.index.set_names(['iter', 'index'])
        # Inverse label encode columns
        data.columns = [col_code_map[int(c[3:])] for c
                        in data.columns]
    return data


@task
def transform_data(
    data: pd.DataFrame,
    cols: Union[None, List[str]] = None,
    transf: str = 'arcsinh',
) -> pd.DataFrame:
    """Transforms columns in `cols` according to specified transformation.
    Transformations available:
    - `log` -- Log transform
    - `arcsinh` -- Inverse hyperbolic sine transform

    Raises:
        ValueError: if `cols` in `data` contain zero values and `transf`
        specified as `log`.
    """

    funcs = {
        'log': np.log,
        'arcsinh': np.arcsinh,
    }
    if transf == 'log' and (data.loc[:, cols] == 0).any().any():
        raise ValueError('Dataset contains zero values. Cannot take logs.')

    if cols:
        cols = [clean_text(col) for col in cols]
        data.loc[:, cols] = (data.loc[:, cols]
                                 .apply(lambda x: funcs[transf](x)))
    return data


@task
def encode_data(data: pd.DataFrame) -> pd.DataFrame:
    """Transforms columns with unordered `category` dtype
    using `pd.get_dummies`. Transforms columns with ordered `category`
    dtype using `series.cat.codes`.

    Note: missing values are ignored (i.e. it is represented by a
    row of zeros for each categorical variable's dummy columns)
    """
    unordered_mask = data.apply(lambda col: is_categorical_dtype(col) and
                                not(col.cat.ordered))
    ordered_mask = data.apply(lambda col: is_categorical_dtype(col) and
                              col.cat.ordered)
    unordered = (data.loc[:, unordered_mask]
                     .columns)
    ordered = (data.loc[:, ordered_mask]
                   .columns)
    if unordered.any():
        dummies = pd.get_dummies(data.loc[:, unordered]).astype('boolean')
        data = (data.loc[:, ~data.columns.isin(unordered)]
                    .join(dummies))
    if ordered.any():
        data.loc[:, ordered] = (data.loc[:, ordered]
                                    .apply(lambda x: x.cat.codes))
    return data


@task
def gelman_standardize_data(data: pd.DataFrame):
    """Standardize data by dividing by 2 standard deviations and
    mean-centering them. Boolean columns are ignored.
    """
    mask = (data.select_dtypes(include=['boolean'])
                .columns)
    data.loc[:, ~mask] = (
        data.loc[:, ~mask].apply(lambda x: x - x.mean())  # Subtract mean
                          .apply(lambda x: x / (2*x.std()))  # Divide by 2 sd
    )
    return data


# Modelling

@task
def run_model(data: pd.DataFrame,
              y: str,
              X: Union[str, List[str]]) -> OLSResults:
    """Runs a linear regression of y on X and returns
    a fitted OLS model in `statsmodels`. Replace the code
    within this function with your own model.
    """
    y, X = clean_text(y), [clean_text(x) for x in X]
    X_with_dummies = [col for col in data.columns if col != y and
                      any(x in col for x in X)]
    mod = sm.OLS(data[y], data[X_with_dummies])
    res = mod.fit()
    return res


# Post-processing

@task
def plot_confidence_intervals(res: OLSResults) -> str:
    """Returns a matplotlib axes containing a box and whisker
    Seaborn plot of regression coefficients' point estimates and
    confidence intervals.

    Set the plot's colour palette using `palette`.
    For a full list of colour palettes in Seaborn, check out:
    medium.com/@morganjonesartist/color-guide-to-seaborn-palettes-da849406d44f
    """
    alt.themes.register("streamlit", streamlit_theme)  # Enable custom theme
    alt.themes.enable("streamlit")
    conf_int = res.conf_int()  # 95% C.I.
    # Stack lower and upper columns
    conf_int = conf_int.stack()
    conf_int.name = "estimate"
    conf_int = pd.DataFrame(conf_int)
    conf_int = (conf_int.reset_index()
                        .rename(columns={'level_0': 'regressor',
                                         'level_1': 'interval'}))
    chart = alt.Chart(conf_int).mark_boxplot().encode(
        x='regressor:O',
        y='estimate:Q'
    ).properties(
        width=200,
        height=500
    )
    return chart


if __name__ == "__main__":
    pass
