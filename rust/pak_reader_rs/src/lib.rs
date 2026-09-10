//! Lecteur natif Rust d'archives `.pak` BG3 (LSPK), miroir de
//! `bg3_mod_tui/pak_reader.py` — s'appuie sur la crate `bg3rustpaklib`
//! (vérifiée sur crates.io, MIT, faite pour BG3/LSPK v15-18) plutôt que de
//! reparser le format bas niveau, et expose une API Python via PyO3 dont
//! la forme suit celle du module Python pur : mêmes exceptions
//! (`PakReaderError` / `UnsupportedPakVersion` / `CorruptedPak`), mêmes
//! fonctions d'extraction d'identité de mod (meta.lsx/meta.lsf).
//!
//! Outil de comparaison uniquement (scripts/compare_pak_reader.py) : non
//! câblé dans pak_metadata.py pour l'instant.

use bg3rustpaklib::{Package, PackagedFile, PakError};
use pyo3::exceptions::PyException;
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use regex::Regex;
use std::path::Path;
use std::sync::OnceLock;

pyo3::create_exception!(pak_reader_rs, PakReaderError, PyException);
pyo3::create_exception!(pak_reader_rs, UnsupportedPakVersion, PakReaderError);
pyo3::create_exception!(pak_reader_rs, CorruptedPak, PakReaderError);

fn map_pak_error(err: PakError) -> PyErr {
    match err {
        PakError::NotAPakFile(_) | PakError::UnsupportedVersion(_) => {
            UnsupportedPakVersion::new_err(err.to_string())
        }
        other => CorruptedPak::new_err(other.to_string()),
    }
}

fn compression_method_code(file: &PackagedFile) -> u8 {
    file.compression_method().to_flags() & 0x0F
}

#[pyclass(module = "pak_reader_rs", from_py_object)]
#[derive(Clone)]
struct PakFileEntry {
    #[pyo3(get)]
    name: String,
    #[pyo3(get)]
    offset: u64,
    #[pyo3(get)]
    size_on_disk: u64,
    #[pyo3(get)]
    uncompressed_size: u64,
    #[pyo3(get)]
    compression_method: u8,
}

impl PakFileEntry {
    fn from_packaged(file: &PackagedFile) -> Self {
        PakFileEntry {
            name: file.name().replace('\\', "/"),
            offset: 0, // bg3rustpaklib n'expose pas l'offset brut ; non utilisé par read()
            size_on_disk: file.compressed_size(),
            uncompressed_size: file.size(),
            compression_method: compression_method_code(file),
        }
    }
}

#[pyclass(module = "pak_reader_rs", unsendable)]
struct PakArchive {
    package: Package,
}

#[pymethods]
impl PakArchive {
    #[staticmethod]
    fn open(path: &str) -> PyResult<Self> {
        let package = Package::open(Path::new(path)).map_err(map_pak_error)?;
        Ok(PakArchive { package })
    }

    #[getter]
    fn version(&self) -> u32 {
        self.package.metadata().version.as_u32()
    }

    fn entries(&self) -> Vec<PakFileEntry> {
        self.package
            .files()
            .iter()
            .map(PakFileEntry::from_packaged)
            .collect()
    }

    fn find(&self, internal_path: &str) -> Option<PakFileEntry> {
        let normalized = internal_path.replace('\\', "/");
        self.package
            .get(&normalized)
            .map(PakFileEntry::from_packaged)
    }

    fn find_suffix(&self, suffix: &str) -> Option<PakFileEntry> {
        let suffix_lower = suffix.replace('\\', "/").to_lowercase();
        self.package
            .files()
            .iter()
            .find(|f| {
                f.name()
                    .replace('\\', "/")
                    .to_lowercase()
                    .ends_with(&suffix_lower)
            })
            .map(PakFileEntry::from_packaged)
    }

    fn read<'py>(&self, py: Python<'py>, entry: &PakFileEntry) -> PyResult<Bound<'py, PyBytes>> {
        let normalized = entry.name.clone();
        let file = self
            .package
            .get(&normalized)
            .ok_or_else(|| CorruptedPak::new_err(format!("entrée introuvable: {normalized}")))?;
        let data = self.package.read_file(file).map_err(map_pak_error)?;
        Ok(PyBytes::new(py, &data))
    }

    fn close(&self) {}

    fn __enter__(slf: Py<Self>) -> Py<Self> {
        slf
    }

    fn __exit__(
        &self,
        _exc_type: Option<Bound<'_, PyAny>>,
        _exc_value: Option<Bound<'_, PyAny>>,
        _traceback: Option<Bound<'_, PyAny>>,
    ) {
    }
}

/// Extrait `(UUID, Name, Folder)` du nœud `ModuleInfo` d'un `meta.lsx` déjà
/// en mémoire — miroir de `pak_reader.parse_meta_lsx_bytes` : ignore
/// volontairement tout UUID sous `Dependencies` en ciblant précisément le
/// nœud `id="ModuleInfo"`. `None` si le XML est invalide ou sans UUID.
#[pyfunction]
fn parse_meta_lsx_bytes(data: &[u8]) -> Option<(String, String, String)> {
    let text = std::str::from_utf8(data).ok()?;
    let doc = roxmltree::Document::parse(text).ok()?;
    let module_info = doc
        .descendants()
        .find(|n| n.has_tag_name("node") && n.attribute("id") == Some("ModuleInfo"))?;

    let mut uuid: Option<String> = None;
    let mut name: Option<String> = None;
    let mut folder: Option<String> = None;
    for attr_node in module_info
        .children()
        .filter(|n| n.has_tag_name("attribute"))
    {
        match attr_node.attribute("id") {
            Some("UUID") => uuid = attr_node.attribute("value").map(str::to_string),
            Some("Name") => name = attr_node.attribute("value").map(str::to_string),
            Some("Folder") => folder = attr_node.attribute("value").map(str::to_string),
            _ => {}
        }
    }
    uuid.map(|u| (u, name.unwrap_or_default(), folder.unwrap_or_default()))
}

fn uuid_regex() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
            .expect("regex UUID valide")
    })
}

fn find_uuids(data: &[u8]) -> Vec<String> {
    let text = String::from_utf8_lossy(data);
    uuid_regex()
        .find_iter(&text)
        .map(|m| m.as_str().to_string())
        .collect()
}

/// Extrait l'UUID du mod depuis le contenu brut d'un `meta.lsf` — miroir de
/// `pak_reader.extract_uuid_from_lsf_bytes` : recherche directe par regex,
/// puis repli sur une décompression deflate brute (les deux variantes de
/// wbits, comme côté Python) si rien n'est trouvé en clair.
#[pyfunction]
fn extract_uuid_from_lsf_bytes(data: &[u8]) -> Option<String> {
    let direct = find_uuids(data);
    if let Some(first) = direct.into_iter().next() {
        return Some(first);
    }
    if data.len() <= 8 {
        return None;
    }
    let payload = &data[8..];
    for zlib_header in [false, true] {
        let mut decompress = flate2::Decompress::new(zlib_header);
        let mut out = Vec::with_capacity(payload.len() * 4);
        let mut buf = vec![0u8; 64 * 1024];
        let mut input_pos = 0usize;
        let mut ok = true;
        loop {
            match decompress.decompress(
                &payload[input_pos..],
                &mut buf,
                flate2::FlushDecompress::None,
            ) {
                Ok(status) => {
                    let produced = decompress.total_out() as usize - out.len();
                    out.extend_from_slice(&buf[..produced]);
                    input_pos = decompress.total_in() as usize;
                    if status == flate2::Status::StreamEnd || input_pos >= payload.len() {
                        break;
                    }
                }
                Err(_) => {
                    ok = false;
                    break;
                }
            }
        }
        if ok {
            if let Some(found) = find_uuids(&out).into_iter().next() {
                return Some(found);
            }
        }
    }
    None
}

/// Ouvre `pak_path`, retourne `(suffixe, contenu brut)` du premier
/// `meta.lsx` trouvé, sinon du premier `meta.lsf` — miroir de
/// `pak_reader.read_meta_lsx_or_lsf_bytes`.
#[pyfunction]
fn read_meta_lsx_or_lsf_bytes<'py>(
    py: Python<'py>,
    pak_path: &str,
) -> PyResult<Option<(String, Bound<'py, PyBytes>)>> {
    let package = Package::open(Path::new(pak_path)).map_err(map_pak_error)?;
    if let Some(lsx) = find_by_suffix(&package, "meta.lsx") {
        let data = package.read_file(lsx).map_err(map_pak_error)?;
        return Ok(Some(("lsx".to_string(), PyBytes::new(py, &data))));
    }
    if let Some(lsf) = find_by_suffix(&package, "meta.lsf") {
        let data = package.read_file(lsf).map_err(map_pak_error)?;
        return Ok(Some(("lsf".to_string(), PyBytes::new(py, &data))));
    }
    Ok(None)
}

fn find_by_suffix<'a>(package: &'a Package, suffix: &str) -> Option<&'a PackagedFile> {
    let suffix_lower = suffix.to_lowercase();
    package.files().iter().find(|f| {
        f.name()
            .replace('\\', "/")
            .to_lowercase()
            .ends_with(&suffix_lower)
    })
}

/// Équivalent natif Rust de `pak_metadata._read_pak_identity_native` :
/// ouvre `pak_path`, localise son `meta.lsx`/`meta.lsf` et en extrait
/// `(UUID, Name)`. `None` si le .pak est lisible mais sans métadonnées de
/// mod exploitables ; lève `PakReaderError` (ou sous-classe) sinon.
#[pyfunction]
fn read_pak_identity_native(pak_path: &str) -> PyResult<Option<(String, String)>> {
    let package = Package::open(Path::new(pak_path)).map_err(map_pak_error)?;
    if let Some(lsx) = find_by_suffix(&package, "meta.lsx") {
        let data = package.read_file(lsx).map_err(map_pak_error)?;
        return Ok(parse_meta_lsx_bytes(&data).map(|(uuid, name, _folder)| (uuid, name)));
    }
    if let Some(lsf) = find_by_suffix(&package, "meta.lsf") {
        let data = package.read_file(lsf).map_err(map_pak_error)?;
        return Ok(extract_uuid_from_lsf_bytes(&data).map(|uuid| (uuid, String::new())));
    }
    Ok(None)
}

#[pymodule]
fn pak_reader_rs(py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("PakReaderError", py.get_type::<PakReaderError>())?;
    m.add(
        "UnsupportedPakVersion",
        py.get_type::<UnsupportedPakVersion>(),
    )?;
    m.add("CorruptedPak", py.get_type::<CorruptedPak>())?;
    m.add_class::<PakArchive>()?;
    m.add_class::<PakFileEntry>()?;
    m.add_function(wrap_pyfunction!(parse_meta_lsx_bytes, m)?)?;
    m.add_function(wrap_pyfunction!(extract_uuid_from_lsf_bytes, m)?)?;
    m.add_function(wrap_pyfunction!(read_meta_lsx_or_lsf_bytes, m)?)?;
    m.add_function(wrap_pyfunction!(read_pak_identity_native, m)?)?;
    Ok(())
}
