from starlette.responses import JSONResponse

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

async def map_values(request):

    request = {
        "PIMProductId": "12345",
        "BarcodeCollection": ["5901234123457", "5901234123458"],
        "Name": "Sample Product",
        "Brand": "Sample Brand",
        "ProducerNumber": "SP-001",
        "ProductManager": "John Doe",
        "ProductAssistant": "Jane Smith"
    }


    output = {
        "PIMProductId": request["PIMProductId"],
        "Brand": request["Brand"],
        "CategoryMapCollection": {"SalesChannelId": 1, "CategoryCollection": {CategoryId}},
        "ProductType": "Smartphone",
        "NameEN": request["Name"] + " EN",
        "NameDE": request["Name"] + " DE",
        "TranslationCollection": [{
            "Langue": "EN",
            "ProductName": request["Name"] + " EN",
        }],
        "SferisName": request["Name"] + " Sferis",
        "CNCode": "85171200",
        "PKWiU": "26.20.11",
        "Intrastatname": request["Name"] + " Intrastat",
        "IntrastatnameLong": request["Name"] + " Intrastat Long",
        "CountryOfOrigin": "Poland",
        "Weight": 0.5,
        "Height": 15.0,
        "Width": 7.0,
        "Depth": 0.8,
        "ProducerGPSR": {
            "NazwaProducenta": "Samsung",
            "Ulica": "ul. Przykładowa",
            "NrDomu": "12",
            "KodPocztowy": "00-001",
            "Miasto": "Warszawa",
            "Kraj": "PL",
            "NrKierunkowy": "+48",
            "NrTelefonu": "123456789",
            "Email": "kontakt@samsung.pl"
        },
        "ImporterGPSR": {
            "NazwaProducenta": "Samsung",
            "Ulica": "ul. Przykładowa",
            "NrDomu": "12",
            "KodPocztowy": "00-001",
            "Miasto": "Warszawa",
            "Kraj": "PL",
            "NrKierunkowy": "+48",
            "NrTelefonu": "123456789",
            "Email": "kontakt@samsung.pl"
        },
        "Piktograms": [PIKTOGRAMY[851074], PIKTOGRAMY[830908]],
        "EnergyLabel": "A++",
        "Battery100Wh": False,
        "InstalledBattery": True,
        "LooseBattery": False,
        "Large": False,
        "ComponentCollection": [
            {"ComponentItemID": "comp1", "ComponentQty": 1},
        ],
        "RelatedProductCollection": [{
            "ProductNumber": "98765",
            "RelationType": "Related" if True else "Duplicate",
            "RelationNo": 1
        }],
        "Speccollection": [{'sectionId': 2,
        'atributeId': 4,
        'value': 200,
        'languageId': 'en'},
        {'sectionId': 2,
        'atributeId': 4,
        'value': 200,
        'languageId': 'de'},
        {'sectionId': 2,
        'atributeId': 5,
        'value': 300,
        'languageId': 'en'},
        ],
        "Photocollection": [
            {"URL": "http://example.com/photo1.jpg"},
            {"URL": "http://example.com/photo2.jpg"}
        ]
    }
    return JSONResponse({
        'success': True,
    })
