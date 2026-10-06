# Captura reproducible de ocho referencias oficiales DANE para el ETL.
# Ejecutar desde PowerShell: ./scripts/capturar_catalogos_dane.ps1
# Escribe únicamente data/reference; conserva intactas las fuentes Bronze y Silver.
# Las URLs fueron verificadas en el directorio oficial del DANE el 6 de octubre de 2026.
# El año nominal de un catálogo no prueba continuidad de límites entre periodos.

$ErrorActionPreference = 'Stop'
# La ubicación del propio script determina la raíz, sin depender del directorio de la terminal.
$raizEvidencia = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
# Todas las salidas se guardan en la carpeta de referencias territoriales del proyecto.
$directorioEvidencia = [IO.Path]::GetFullPath((Join-Path $raizEvidencia 'data\reference'))
# Comprobamos que la carpeta calculada permanezca dentro de esta raíz del proyecto.
$prefijoRaiz = $raizEvidencia.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
if (-not $directorioEvidencia.StartsWith($prefijoRaiz, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'La ruta de referencias debe permanecer dentro del proyecto.'
}
New-Item -ItemType Directory -Path $directorioEvidencia -Force | Out-Null
# Cada petición debe producir JSON válido sin la estructura de error de ArcGIS.
function Obtener-JsonDane([string]$uri) {
    $respuesta = Invoke-RestMethod -Uri $uri -TimeoutSec 45
    if ($null -ne $respuesta.error) {
        throw ('Error oficial DANE: ' + ($respuesta.error | ConvertTo-Json -Compress))
    }
    return $respuesta
}
# Se usa UTF-8 sin BOM. El hash SHA-256 y el tamaño corresponden a los bytes guardados.
function Guardar-JsonDane($objeto, [string]$nombre) {
    # Solo aceptamos nombres de archivo, sin subcarpetas ni rutas externas.
    if ([IO.Path]::GetFileName($nombre) -ne $nombre) {
        throw 'La salida debe tener un nombre simple dentro de data/reference.'
    }
    $ruta = Join-Path $directorioEvidencia $nombre
    $contenido = $objeto | ConvertTo-Json -Depth 40
    [IO.File]::WriteAllText($ruta, $contenido, [Text.UTF8Encoding]::new($false))
    return [ordered]@{
        archivo = 'data/reference/' + $nombre
        sha256 = (Get-FileHash -LiteralPath $ruta -Algorithm SHA256).Hash.ToLowerInvariant()
        tamano_bytes = (Get-Item -LiteralPath $ruta).Length
    }
}
# Definimos explícitamente las ocho capas verificadas y sus campos reales.
# En 2018 la capa Municipios contiene también ANM: su tipo se deja sin resolver.
# La capa ANM es la evidencia específica para esa categoría; sus duplicados exactos
# se resuelven con prioridad ANM en el lector, conservando ambos archivos originales.
# En 2019 el servicio se acredita por su descripción oficial de versión 2019.
# MPIO_NANO identifica el año de actualización de cada geometría y contiene valores
# 2018/2019; no se usa para recortar la capa, porque dejaría solo los dos cambios.
# Se usa MPIO_CCNCTNDO, que publica el código municipal completo de cinco dígitos.
# En 2020–2024 se usa el código completo MPIO_CDPMP, no el sufijo MPIO_CCDGO.
$fuentesDane = @(
  [ordered]@{anio=2018;nombre='dane_divipola_2018_municipios';servidor='https://geoportal.dane.gov.co/mparcgis/rest/services/Divipola/Serv_DeptosMpiosANM_2018/MapServer';capa=1;criterio_temporal='capa_anual';tipo_por_capa=$null;columnas=[ordered]@{codigo='MPIO_CCDGO';departamento='DPTO_CCDGO';nombre='MPIO_CNMBR'}},
  [ordered]@{anio=2018;nombre='dane_divipola_2018_anm';servidor='https://geoportal.dane.gov.co/mparcgis/rest/services/Divipola/Serv_DeptosMpiosANM_2018/MapServer';capa=2;criterio_temporal='capa_anual';tipo_por_capa='area_no_municipalizada';columnas=[ordered]@{codigo='MPIO_CCDGO';departamento='DPTO_CCDGO';nombre='MPIO_CNMBR'}},
  [ordered]@{anio=2019;nombre='dane_mgn_2019_municipios';servidor='https://geoportal.dane.gov.co/mparcgis/rest/services/MGN2019/Serv_CapasMGN_2019/MapServer';capa=317;criterio_temporal='capa_anual';columnas=[ordered]@{codigo='MPIO_CCNCTNDO';departamento='DPTO_CCDGO';nombre='MPIO_CNMBRE';nombre_departamento='DPTO_CNMBRE';anio_registro='MPIO_NANO'}},
  [ordered]@{anio=2020;nombre='dane_mgn_2020_municipios';servidor='https://geoportal.dane.gov.co/mparcgis/rest/services/MGN2020/Serv_CapasMGN_2020/MapServer';capa=317;criterio_temporal='anio_registro';columnas=[ordered]@{codigo='MPIO_CDPMP';departamento='DPTO_CCDGO';nombre='MPIO_CNMBRE';nombre_departamento='DPTO_CNMBRE';tipo='MPIO_TIPO';anio_registro='MPIO_VGNC'}},
  [ordered]@{anio=2021;nombre='dane_mgn_2021_municipios';servidor='https://geoportal.dane.gov.co/mparcgis/rest/services/MGN2021/Serv_CapasMGN_2021/MapServer';capa=317;criterio_temporal='anio_registro';columnas=[ordered]@{codigo='MPIO_CDPMP';departamento='DPTO_CCDGO';nombre='MPIO_CNMBRE';nombre_departamento='DPTO_CNMBRE';tipo='MPIO_TIPO';anio_registro='MPIO_VGNC'}},
  [ordered]@{anio=2022;nombre='dane_mgn_2022_municipios';servidor='https://geoportal.dane.gov.co/mparcgis/rest/services/MGN2022/Serv_CapasMGN_2022/MapServer';capa=317;criterio_temporal='anio_registro';columnas=[ordered]@{codigo='MPIO_CDPMP';departamento='DPTO_CCDGO';nombre='MPIO_CNMBRE';nombre_departamento='DPTO_CNMBRE';tipo='MPIO_TIPO';anio_registro='MPIO_NANO'}},
[ordered]@{anio=2023;nombre='dane_mgn_2023_municipios';servidor='https://geoportal.dane.gov.co/mparcgis/rest/services/MGN2023/Serv_CapasMGN_2023/MapServer';capa=317;criterio_temporal='anio_registro';columnas=[ordered]@{codigo='MPIO_CDPMP';departamento='DPTO_CCDGO';nombre='MPIO_CNMBRE';nombre_departamento='DPTO_CNMBRE';tipo='MPIO_TIPO';anio_registro='MPIO_NANO'}},
[ordered]@{anio=2024;nombre='dane_divipola_2024_municipios';servidor='https://geoportal.dane.gov.co/mparcgis/rest/services/Divipola/Serv_DIVIPOLA_MGN_2024/MapServer';capa=317;criterio_temporal='anio_registro';columnas=[ordered]@{codigo='MPIO_CDPMP';departamento='DPTO_CCDGO';nombre='MPIO_CNMBRE';nombre_departamento='DPTO_CNMBRE';tipo='MPIO_TIPO';anio_registro='MPIO_NANO'}})
# Las dos capas 2018 comparten servicio; consultamos esa ficha una sola vez.
$cacheServiciosDane = @{}
$catalogosDane = [Collections.Generic.List[object]]::new()
# Procesamos cada catálogo por separado y conservamos su URL y metadatos de procedencia.
foreach ($fuente in $fuentesDane) {
 $baseCapa = $fuente.servidor + '/' + $fuente.capa
 $fichaCapa = Obtener-JsonDane ($baseCapa + '?f=pjson')
 if (-not $cacheServiciosDane.ContainsKey($fuente.servidor)) { $cacheServiciosDane[$fuente.servidor] = Obtener-JsonDane ($fuente.servidor + '?f=pjson') }
 # Si el servicio cambia su esquema, detenemos la captura antes de asignarle
 # los nombres de columnas registrados originalmente en el manifiesto.
 $camposPublicados = @($fichaCapa.fields | ForEach-Object { $_.name })
 foreach ($campoEsperado in $fuente.columnas.Values) {
  if ($campoEsperado -notin $camposPublicados) {
   throw ('Cambio de esquema: ' + $fuente.nombre + ' no contiene ' + $campoEsperado)
  }
 }
 # La evidencia de 2018 se apoya en una descripción anual explícita, no en la URL.
  if ($fuente.criterio_temporal -eq 'capa_anual') {
   $fichaServicio = $cacheServiciosDane[$fuente.servidor]
   $descripcionTemporal = [string]$fichaServicio.serviceDescription + ' ' + [string]$fichaServicio.documentInfo.Title
   if ($descripcionTemporal -notmatch ('(?<!\d)' + $fuente.anio + '(?!\d)')) {
    throw ('El servicio ' + $fuente.anio + ' ya no publica la descripción temporal verificada.')
  }
 }
 # El conteo oficial se compara con la lista de identificadores y los atributos descargados.
  $where = if ($fuente.Contains('filtro')) { [uri]::EscapeDataString([string]$fuente.filtro) } else { '1%3D1' }
  $conteo = Obtener-JsonDane ($baseCapa + '/query?where=' + $where + '&returnCountOnly=true&f=pjson')
  $rIds = Obtener-JsonDane ($baseCapa + '/query?where=' + $where + '&returnIdsOnly=true&f=pjson')
 $ids = @($rIds.objectIds | Sort-Object)
 if ($ids.Count -eq 0 -or $ids.Count -ne [int]$conteo.count -or @($ids | Sort-Object -Unique).Count -ne $ids.Count) { throw ('Conteo/IDs incompletos: ' + $fuente.nombre) }
 # Conservamos los atributos publicados. No descargamos geometría ni reinterpretamos territorios.
 $features = [Collections.Generic.List[object]]::new()
 $paginaInicial = $null
 $peticiones = [Collections.Generic.List[object]]::new()
 # ArcGIS puede truncar consultas. Los lotes de 500 están por debajo del límite
 # mínimo de estas capas y se verifican uno por uno, sin asumir paginación disponible.
 for ($posicion = 0; $posicion -lt $ids.Count; $posicion += 500) {
  $fin = [Math]::Min($posicion + 499, $ids.Count - 1)
  $loteIds = @($ids[$posicion..$fin])
  $uriPagina = $baseCapa + '/query?objectIds=' + ($loteIds -join ',') + '&outFields=*&returnGeometry=false&f=pjson'
  $pagina = Obtener-JsonDane $uriPagina
  if ($pagina.exceededTransferLimit -eq $true) { throw ('Pagina truncada: ' + $fuente.nombre) }
  if (@($pagina.features).Count -ne $loteIds.Count) { throw ('Faltan atributos en pagina: ' + $fuente.nombre) }
  if ($null -eq $paginaInicial) { $paginaInicial = $pagina }
  foreach ($feature in @($pagina.features)) { if ($null -eq $feature.attributes) { throw 'Feature sin atributos' }; $features.Add($feature) }
  $peticiones.Add([ordered]@{metodo='objectIds';cantidad_ids=$loteIds.Count;cantidad_features=@($pagina.features).Count;exceededTransferLimit=($pagina.exceededTransferLimit -eq $true)})
 }
 # Una descarga se acepta solo si los identificadores son únicos, coinciden
 # exactamente con los consultados y su cantidad coincide con el conteo oficial.
 $campoOid = $rIds.objectIdFieldName
 $idsDescargados = @($features | ForEach-Object { $_.attributes.$campoOid })
 if ($features.Count -ne [int]$conteo.count -or @($idsDescargados | Sort-Object -Unique).Count -ne $features.Count -or @(Compare-Object $ids $idsDescargados).Count -ne 0) { throw ('Validacion final de IDs fallo: ' + $fuente.nombre) }
  # En 2019–2024 comprobamos la versión de TODOS los registros antes de guardarlos.
 # Así una futura actualización del mismo endpoint no acredita otro año por error.
 if ($fuente.criterio_temporal -eq 'anio_registro') {
  $campoAnio = $fuente.columnas.anio_registro
  foreach ($feature in $features) {
   $anioPublicado = $feature.attributes.$campoAnio
   if ($null -eq $anioPublicado -or $anioPublicado -ne $fuente.anio) {
    throw ('Año de registro diferente al esperado: ' + $fuente.nombre)
   }
  }
 }
 # Unimos las páginas en un envelope ArcGIS fields/features sin alterar attributes.
 $resultadoDatos = [ordered]@{}
 foreach ($propiedad in $paginaInicial.PSObject.Properties) { if ($propiedad.Name -ne 'features' -and $propiedad.Name -ne 'exceededTransferLimit') { $resultadoDatos[$propiedad.Name] = $propiedad.Value } }
 $resultadoDatos.features = $features.ToArray()
 $resultadoDatos.exceededTransferLimit = $false
 # La fecha de captura documenta cuándo obtuvimos la evidencia, no la creación municipal.
 $capturado = [DateTime]::UtcNow.ToString('o')
  $comprobacion = [ordered]@{conteo_oficial=[int]$conteo.count;cantidad_ids=$ids.Count;cantidad_features=$features.Count;ids_unicos=$true;ids_coincidentes=$true;consulta_completa=$true;filtro_aplicado=($fuente.filtro);consulta_conteo=($baseCapa+'/query?where='+$where+'&returnCountOnly=true&f=pjson');consulta_ids=($baseCapa+'/query?where='+$where+'&returnIdsOnly=true&f=pjson');paginas=$peticiones.ToArray()}
 # La ficha original del servicio/capa y el control de descarga se guardan aparte.
 $metadata = [ordered]@{capturado_en_utc=$capturado;referencia_servicio=$fuente.servidor;referencia_capa=$baseCapa;servicio=$cacheServiciosDane[$fuente.servidor];capa=$fichaCapa;verificacion_descarga=$comprobacion}
 # Publicamos los archivos y registramos sus hashes en el manifiesto de esta ejecución.
 $datosArchivo = Guardar-JsonDane $resultadoDatos ($fuente.nombre + '.json')
 $metadataArchivo = Guardar-JsonDane $metadata ($fuente.nombre + '_metadata.json')
 $entrada = [ordered]@{anio=$fuente.anio;referencia=$baseCapa;criterio_temporal=$fuente.criterio_temporal;archivo=$datosArchivo.archivo;sha256=$datosArchivo.sha256;tamano_bytes=$datosArchivo.tamano_bytes;columnas=$fuente.columnas;numero_registros=$features.Count;capturado_en_utc=$capturado;metadata=$metadataArchivo;verificacion_descarga=$comprobacion}
  if ($fuente.Contains('tipo_por_capa')) { $entrada.tipo_por_capa = $fuente.tipo_por_capa }
  if ($fuente.Contains('filtro')) { $entrada.filtro = $fuente.filtro }
 $catalogosDane.Add($entrada)
 Write-Output ('Capturado ' + $fuente.nombre + ': ' + $features.Count + ' registros, ' + $datosArchivo.tamano_bytes + ' bytes, SHA256 ' + $datosArchivo.sha256)
}
# El manifiesto enlaza cada referencia con su año, criterio, esquema, bytes y SHA-256.
# Las referencias son para años exactos; no autorizan interpolaciones ni remapeos históricos.
$manifiestoDane = [ordered]@{version_manifiesto='1.0';entidad='DANE';capturado_en_utc=[DateTime]::UtcNow.ToString('o');alcance='Identidad codigo-departamento en el anio exacto de cada snapshot; sin interpolacion ni remapeo de territorios historicos';catalogos_anuales=$catalogosDane.ToArray()}
$manifiestoArchivo = Guardar-JsonDane $manifiestoDane 'catalogos_dane.json'
Write-Output ('Manifiesto guardado: ' + $manifiestoArchivo.archivo)
