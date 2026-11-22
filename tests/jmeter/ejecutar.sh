#!/usr/bin/env bash
# Uso:  ./ejecutar.sh local            -> prueba de carga contra http://localhost:8000
#       ./ejecutar.sh nube URL_HOST    -> estrés escalonado contra la app desplegada (ej. aquaplants.onrender.com)
set -euo pipefail
cd "$(dirname "$0")"; MODO=${1:-local}; export JVM_ARGS="-Duser.timezone=UTC"
JM=${JMETER:-jmeter}
corre() { # nombre hilos_disp hilos_usr duracion rampa [args extra]
  local n=$1; shift; rm -rf "resultados/$n"; mkdir -p "resultados/$n"
  $JM -n -t aquaplants_carga.jmx -l "resultados/$n/resultados.jtl" -e -o "resultados/$n/informe" \
      -Jhilos_disp=$1 -Jhilos_usr=$2 -Jduracion=$3 -Jrampa=$4 "${@:5}"
}
case $MODO in
  local)  corre carga_local 20 10 120 30 -Jhost=localhost -Jpuerto=8000 -Jprotocolo=http ;;
  nube)   H=${2:?falta el host}; for n in 10 25 50 100 200; do
            corre "estres_nube_$n" $n $((n/4+1)) 120 30 -Jhost=$H -Jpuerto=443 -Jprotocolo=https -Jpausa_ms=500; sleep 20; done ;;
esac
echo "Informes HTML en tests/jmeter/resultados/*/informe/index.html"
