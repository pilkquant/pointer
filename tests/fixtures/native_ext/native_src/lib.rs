use pyo3::prelude::*;

#[pyfunction]
fn fast_hash(data: &str) -> String {
    format!("hash_{}", data.len())
}

#[pymodule]
fn fastlib(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(fast_hash, m)?)?;
    Ok(())
}
