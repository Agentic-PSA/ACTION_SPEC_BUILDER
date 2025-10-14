from starlette.responses import JSONResponse
from src.services.fill_graph import fill_graph_single_core, convert_units, process_specification, apply_changes

PIKTOGRAMY = {
    851070: "Substancje łatwopalne",
    851071: "Substancje pod ciśnieniem",
    851072: "Drażniące lub szkodliwe",
    851073: "Korozja",
    851074: "Zagrożenie dla środowiska",
    851075: "Poważne zagrożenie dla zdrowia",

    851082: "Toksyczne dla zdrowia",
    851103: "Materiały wybuchowe",
    831752: "GHS01: Substancje wybuchowe",
    830908: "GHS02: Flammable",
    831754: "GHS03: Substancje utleniające",
    831753: "GHS04: Gazy pod ciśnieniem",
    830057: "GHS05: Corrosive",
    831755: "GHS06: Toxic",
    807686: "GHS07: Szkodliwy"
}


async def pim(request):
    data = await request.json()
    # tu możesz uzupełniać dane PIM


    output = await fill_graph_single_core({"body":data})
    return JSONResponse(output)

