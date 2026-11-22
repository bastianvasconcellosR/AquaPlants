"""Genera aquaplants_carga.jmx (Apache JMeter 5.x). Se parametriza por propiedades -J:
host, puerto, protocolo, hilos_disp, hilos_usr, rampa, duracion, pausa_ms, claves (CSV)."""
from xml.sax.saxutils import escape as e

def prop(n, v): return f'<stringProp name="{n}">{e(str(v))}</stringProp>'
def P(n): return "${__P(%s,%s)}"

def http(nombre, metodo, ruta, cuerpo=None, cabeceras=(), extra=""):
    hdr = ""
    if cabeceras:
        hdr = '<HeaderManager guiclass="HeaderPanel" testclass="HeaderManager" testname="Cabeceras" enabled="true"><collectionProp name="HeaderManager.headers">' + "".join(
            f'<elementProp name="" elementType="Header">{prop("Header.name", k)}{prop("Header.value", v)}</elementProp>' for k, v in cabeceras) + "</collectionProp></HeaderManager><hashTree/>"
    body = ""
    if cuerpo is not None:
        body = ('<boolProp name="HTTPSampler.postBodyRaw">true</boolProp><elementProp name="HTTPsampler.Arguments" elementType="Arguments"><collectionProp name="Arguments.arguments">'
                f'<elementProp name="" elementType="HTTPArgument"><boolProp name="HTTPArgument.always_encode">false</boolProp>{prop("Argument.value", cuerpo)}{prop("Argument.metadata", "=")}</elementProp></collectionProp></elementProp>')
    s = (f'<HTTPSamplerProxy guiclass="HttpTestSampleGui" testclass="HTTPSamplerProxy" testname="{e(nombre)}" enabled="true">{body}'
         f'{prop("HTTPSampler.path", ruta)}{prop("HTTPSampler.method", metodo)}<boolProp name="HTTPSampler.follow_redirects">true</boolProp><boolProp name="HTTPSampler.use_keepalive">true</boolProp></HTTPSamplerProxy>')
    return s, hdr + extra

def aserto(codigos):
    return ('<ResponseAssertion guiclass="AssertionGui" testclass="ResponseAssertion" testname="Código HTTP esperado" enabled="true"><collectionProp name="Asserion.test_strings">'
            + "".join(f'<stringProp name="{abs(hash(c))%10**8}">{c}</stringProp>' for c in codigos) +
            '</collectionProp><stringProp name="Assertion.test_field">Assertion.response_code</stringProp><boolProp name="Assertion.assume_success">false</boolProp><intProp name="Assertion.test_type">38</intProp></ResponseAssertion><hashTree/>')

def tg(nombre, hilos, hijos):
    return (f'<ThreadGroup guiclass="ThreadGroupGui" testclass="ThreadGroup" testname="{e(nombre)}" enabled="true">'
            '<stringProp name="ThreadGroup.on_sample_error">continue</stringProp><elementProp name="ThreadGroup.main_controller" elementType="LoopController" guiclass="LoopControlPanel" testclass="LoopController" enabled="true"><boolProp name="LoopController.continue_forever">false</boolProp><intProp name="LoopController.loops">-1</intProp></elementProp>'
            f'{prop("ThreadGroup.num_threads", hilos)}{prop("ThreadGroup.ramp_time", "${__P(rampa,30)}")}<boolProp name="ThreadGroup.scheduler">true</boolProp>{prop("ThreadGroup.duration", "${__P(duracion,120)}")}{prop("ThreadGroup.delay", "0")}</ThreadGroup><hashTree>{hijos}</hashTree>')

def sam(par, hijos=""):
    return par[0] + "<hashTree>" + par[1] + hijos + "</hashTree>"

pausa = '<ConstantTimer guiclass="ConstantTimerGui" testclass="ConstantTimer" testname="Pausa entre envíos" enabled="true">' + prop("ConstantTimer.delay", "${__P(pausa_ms,1000)}") + '</ConstantTimer><hashTree/>'

csv = ('<CSVDataSet guiclass="TestBeanGUI" testclass="CSVDataSet" testname="Sensores y API Keys (claves.csv)" enabled="true">' + prop("filename", "${__P(claves,claves.csv)}") +
       prop("variableNames", "api_key,variable,minimo,maximo") + prop("delimiter", ",") + '<boolProp name="ignoreFirstLine">true</boolProp><boolProp name="recycle">true</boolProp><boolProp name="stopThread">false</boolProp>' + prop("shareMode", "shareMode.all") + '</CSVDataSet><hashTree/>')

# Grupo A: dispositivos enviando mediciones (marca de tiempo única hacia el pasado: la API resuelve a 1 s y rechaza duplicados)
cuerpo_med = '{"variable":"${variable}","valor":${__groovy(def a=vars.get(\'minimo\') as double; def b=vars.get(\'maximo\') as double; Math.round((a+Math.random()*(b-a))*100)/100.0)},"marca_tiempo":"${__timeShift(yyyy-MM-dd\'T\'HH:mm:ss\'Z\',,PT-${__counter(FALSE,)}S,,)}"}'
ingesta = sam(http("POST /mediciones (dispositivo)", "POST", "/api/v1/mediciones", cuerpo_med, [("Content-Type", "application/json"), ("X-API-Key", "${api_key}")], aserto([201])))
gA = tg("Dispositivos AquaBrain (ingesta)", "${__P(hilos_disp,20)}", csv + ingesta + pausa)

# Grupo B: usuarios del dashboard (login una vez por hilo, luego consultas)
login = sam(http("POST /auth/login", "POST", "/api/v1/auth/login", '{"email":"${__P(email,supervisor@aquaplants.cl)}","clave":"${__P(clave,Super2026aq)}"}', [("Content-Type", "application/json")], aserto([200])),
            '<JSONPostProcessor guiclass="JSONPostProcessorGui" testclass="JSONPostProcessor" testname="Extraer token" enabled="true">' + prop("JSONPostProcessor.referenceNames", "token") + prop("JSONPostProcessor.jsonPathExprs", "$.token") + prop("JSONPostProcessor.match_numbers", "1") + '</JSONPostProcessor><hashTree/>')
aut = [("Authorization", "Bearer ${token}")]
bucle = ('<LoopController guiclass="LoopControlPanel" testclass="LoopController" testname="Consultas del panel" enabled="true"><boolProp name="LoopController.continue_forever">true</boolProp><intProp name="LoopController.loops">-1</intProp></LoopController><hashTree>'
         + sam(http("GET /dashboard/estado", "GET", "/api/v1/dashboard/estado", None, aut, aserto([200]))) + sam(http("GET /alertas", "GET", "/api/v1/alertas", None, aut, aserto([200]))) + pausa + '</hashTree>')
once = '<OnceOnlyController guiclass="OnceOnlyControllerGui" testclass="OnceOnlyController" testname="Login (una vez por usuario)" enabled="true"/><hashTree>' + login + '</hashTree>'
gB = tg("Usuarios del dashboard", "${__P(hilos_usr,10)}", once + bucle)

defaults = ('<ConfigTestElement guiclass="HttpDefaultsGui" testclass="ConfigTestElement" testname="Servidor" enabled="true"><elementProp name="HTTPsampler.Arguments" elementType="Arguments"><collectionProp name="Arguments.arguments"/></elementProp>'
            + prop("HTTPSampler.domain", "${__P(host,localhost)}") + prop("HTTPSampler.port", "${__P(puerto,8000)}") + prop("HTTPSampler.protocol", "${__P(protocolo,http)}")
            + prop("HTTPSampler.connect_timeout", "10000") + prop("HTTPSampler.response_timeout", "30000") + '</ConfigTestElement><hashTree/>')

xml = ('<?xml version="1.0" encoding="UTF-8"?><jmeterTestPlan version="1.2" properties="5.0" jmeter="5.6.3"><hashTree>'
       '<TestPlan guiclass="TestPlanGui" testclass="TestPlan" testname="AquaPlants – carga y estrés" enabled="true"><boolProp name="TestPlan.functional_mode">false</boolProp><boolProp name="TestPlan.serialize_threadgroups">false</boolProp>'
       '<elementProp name="TestPlan.user_defined_variables" elementType="Arguments"><collectionProp name="Arguments.arguments"/></elementProp></TestPlan><hashTree>'
       + defaults + gA + gB + '</hashTree></hashTree></jmeterTestPlan>')
open("aquaplants_carga.jmx", "w", encoding="utf-8").write(xml)
print("aquaplants_carga.jmx", len(xml))
