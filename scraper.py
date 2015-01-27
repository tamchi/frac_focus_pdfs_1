import scraperwiki
import base64
import datetime
import re, StringIO

from pdfminer.pdfparser import PDFParser, PDFDocument, PDFNoOutlines, PDFSyntaxError
from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
from pdfminer.converter import PDFPageAggregator
from pdfminer.layout import LAParams, LTTextBox, LTTextLine, LTFigure, LTImage, LTTextLineHorizontal, LTTextBoxHorizontal, LTChar, LTRect, LTLine
from binascii import b2a_hex
from operator import itemgetter

def pdfextract(pdfbin):
    cin = StringIO.StringIO()
    cin.write(pdfbin)
    cin.seek(0)
    parser = PDFParser(cin)
    doc = PDFDocument()
    parser.set_document(doc)
    try:
        doc.set_parser(parser)
    except PDFSyntaxError, e:
        return [{"npage":npage, "x0":0, "y0":0, "x1":0.099, "y1":0.099, "val":"SyntaxError "+str(e)}]
    doc.initialize("")
    assert doc.is_extractable
    
    rsrcmgr = PDFResourceManager()
    laparams = LAParams()
    device = PDFPageAggregator(rsrcmgr, laparams=laparams)
    interpreter = PDFPageInterpreter(rsrcmgr, device)
    
    boxes = [ ]
    for i, page in enumerate(doc.get_pages()):
        try:
            interpreter.process_page(page)
        except AssertionError, e:
            boxes.append({"npage":i+1, "x0":0, "y0":0, "x1":0.099, "y1":0.099, "val":"AssertionError "+str(e)})
            continue
        layout = device.get_result()

        objs = [ ]
        objstack = list(reversed(layout._objs))
        while objstack:
            obj = objstack.pop()
            if type(obj) in [LTFigure, LTTextBox, LTTextLine, LTTextBoxHorizontal]:
                objstack.extend(reversed(obj._objs))
            elif type(obj) == LTTextLineHorizontal:
                objs.append(obj)
            elif type(obj) == LTLine:
                objs.append(obj)
        print objs
        obj = objs[0]
        print list(obj)
        sys.exit(0)

        xlines = [ (obj.x0, (obj.y0, obj.y1))  for obj in objs  if isinstance(obj, LTLine) and obj.x0 == obj.x1 ]
        ylines = [ (obj.y0, (obj.x0, obj.x1))  for obj in objs  if isinstance(obj, LTLine) and obj.y0 == obj.y1  ]
        xlines.sort()
        ylines.sort()
        for obj in objs:
            if not isinstance(obj, LTTextLineHorizontal):
                continue
            x, y = (obj.x0+obj.x1)/2, (obj.y0+obj.y1)/2
            x0l = [ xline[0]  for xline in xlines  if xline[0]<=x and xline[1][0]<=y<=xline[1][1] ] 
            x1l = [ xline[0]  for xline in xlines  if xline[0]>=x and xline[1][0]<=y<=xline[1][1] ] 
            y0l = [ yline[0]  for yline in ylines  if yline[0]<=y and yline[1][0]<=x<=yline[1][1] ] 
            y1l = [ yline[0]  for yline in ylines  if yline[0]>=y and yline[1][0]<=x<=yline[1][1] ] 
            if x0l:  obj.bx0 = max(x0l)  
            else:  obj.bx0 = obj.x0   
            if x1l:  obj.bx1 = min(x1l)   
            if y0l:  obj.by0 = max(y0l)   
            if y1l:  obj.by1 = min(y1l)   

#        groupboxes(objs)
        #print "page", i, objs
#        boxes.extend(parseobjs(objs, page.mediabox, i+1))
    return boxes



# quick run through collection for now (should be done with a join for missing)
def Main():
    scraperwiki.sqlite.attach("frac_focus_wells")
    while True:
        sql = "wellpdf.API, pdfb64 from wellpdf left join wellinfo on wellinfo.API=wellpdf.API where wellinfo.API is null limit 10"
        sql = "wellpdf.API, pdfb64 from wellpdf limit 10"
        for rec in scraperwiki.sqlite.select(sql):
            ParsePdf(rec["API"], base64.decodestring(rec["pdfb64"]))
        break

def ParsePdf(API, pdfbin):
    print API
    boxes = pdfextract(pdfbin)


    # put all the pages together
    rowtops = { }
    for page in root:
        pagenumber = int(page.attrib.get("number"))
        for text in page:
            if text.tag != "text":
                continue
            top, left, width, height, font = [ int(text.attrib.get(k))  for k in ["top", "left", "width", "height", "font"] ]
            ptop = (pagenumber, top)
            if ptop not in rowtops:
                rowtops[ptop] = [ ]
            rowtops[ptop].append((left, left+width, font, "".join(text.itertext()).strip()))

    # slice out the rows and headings of the two tables
    rowtopi = rowtops.items()
    rowtopi.sort()
    
    idisc, icomp, iend = -1, -1, -1
    i = 0
    while i < len(rowtopi):
        if i+1 < len(rowtopi) and rowtopi[i+1][0][0] == rowtopi[i][0][0] and rowtopi[i+1][0][1] - rowtopi[i][0][1] <= 2:
            #print "joining\n\n", rowtopi[i], "\n\n", rowtopi[i+1]
            rowtopi[i][1].extend(rowtopi[i+1][1])
            del rowtopi[i+1]
            continue

        ktop, row = rowtopi[i]
        row.sort()
        if row[0][3] == 'Hydraulic Fracturing Fluid Product Component Information Disclosure':
            idisc = i
        if re.match('Hydraulic Fracturing Fluid Composition', row[0][3]):
            icomp = i
        if row[0][3] == '* Total Water Volume sources may include fresh water, produced water, and/or recycled water':
            iend = i
        i += 1

    if -1 in [idisc, icomp, iend]:
        print "table ends missing API", API, [idisc, icomp, iend]
        for row in rowtopi:
            print row
        assert False
        

    # extract the info table
    #   some are bad https://views.scraperwiki.com/run/frac_focus_dashboard_1/?pdfapi=42-135-40759
    data = { }
    for ktop, row in rowtopi[idisc+1:icomp]:
        assert row[0][1] in [292,293,314,313,306,305,304,309,317,316,324,303,308,307,389,388], row
        if len(row) == 2:
            assert row[1][1] in [460,461,726,513,483,474,475,476,477,486,481,482,747,493,494,468,473,472,457,456,801,837,736,568,569,664,665,585], row
            val = row[1][3]
        else:
            assert len(row) == 1
            val = ""
        data[row[0][3].strip(":")] = val


    assert data.keys() == ['True Vertical Depth (TVD)', 'Long/Lat Projection', 'Production Type', 'Longitude', 'County', 'API Number', 'State', 'Fracture Date', 'Total Water Volume (gal)*', 'Latitude', 'Operator Name', 'Well Name and Number'], data.keys()

    lAPI = data.pop("API Number")
    assert lAPI.replace("-", "") == API.replace("-", ""), (API, lAPI)
    data["API"] = API
    data["Longitude"] = float(data.pop('Longitude'))
    data["Latitud"] = float(data.pop('Latitude'))
    data["water_gal"] = int(data.pop('Total Water Volume (gal)*').replace(",", ""))
    data["Operator"] = data.pop('Operator Name')
    data["Datum"] = data.pop('Long/Lat Projection')
    data["Well Type"] = data.pop('Production Type')
    mdate = re.match("(\d+)/(\d+)/(\d\d\d\d)", data["Fracture Date"])
    assert mdate, data
    data["Fracture Date"] = datetime.date(int(mdate.group(3)), int(mdate.group(1)), int(mdate.group(2)))
    data["Well Name and Number"] = data.pop("Well Name and Number")
    sdepth = data.pop('True Vertical Depth (TVD)').replace(",", "")
    if sdepth and API not in ["30-039-30942"]:
            # not an int https://views.scraperwiki.com/run/frac_focus_dashboard_1/?pdfapi=30-039-30942
        data["depth"] = int(sdepth)

    # extract the composition table
        # collapse the headings section
    headings = [ [h[0], h[1], h[3]]  for h in rowtopi[icomp+1][1] ]
    for ktop, row in rowtopi[icomp+2:icomp+6]:
        for el in row:
            for heading in headings:
                if el[0] < heading[1] and el[1] > heading[0]:
                    heading[2] = "%s\n%s" % (heading[2], el[3])
                    break
            else:
                assert False, (el, headings)
    lheadings = [ h[2]  for h in headings ]
    #print lheadings
    assert lheadings == ['Trade Name', 'Supplier', 'Purpose', 'Ingredients', 'Chemical Abstract\nService Number\n(CAS #)', 'Maximum\nIngredient\nConcentration\nin Additive\n(% by mass)**', 'Maximum\nIngredient\nConcentration\nin HF Fluid\n(% by mass)**', 'Comments'], lheadings
    headings[4][2] = "CAS"
    headings[5][2] = "MaxConc_in_additive"
    headings[6][2] = "MaxConc_in_fluid"

    headings[3][0] -= 74   # [345, 414, 'Purpose'], [550, 643, 'Ingredients'], [736, 888, 'CAS']
    headings[3][1] += 70   # needs to expand the width of this cell enough to capture the contents
    headings[2][0] -= 64   # [345, 414, 'Purpose'], [550, 643, 'Ingredients'], [736, 888, 'CAS']
    headings[2][1] += 30   # needs to expand the width of this cell enough to capture the contents
    headings[1][0] -= 4   
    headings[0][0] -= 40   

    # match up the headings to the data in the columns
    ldata = [ ]
    for ktop, row in rowtopi[icomp+6:iend]:
        #print ktop, row

        cdata = { }
        for el in row:
            for heading in headings:
                if el[0] < heading[1] and el[1] > heading[0]:
                    cdata[heading[2]] = el[3]
                    break
            else:
                assert False, (el, headings)
        #print cdata

        if not cdata.get('MaxConc_in_fluid') and not cdata.get('MaxConc_in_additive'):
            for kc in ["Trade Name", "Supplier", "Purpose", "Ingredients"]:
                if cdata.get(kc):
                    ldata[-1][kc] = "%s %s" % (ldata[-1][kc], cdata[kc])
            continue

        cdata["API"] = API

        if not cdata.get("Trade Name"):
            assert not cdata.get("Supplier") and not cdata.get("Purpose"), cdata
            cdata["Trade Name"] = ldata[-1]["Trade Name"]
            cdata["Supplier"] = ldata[-1]["Supplier"]
            cdata["Purpose"] = ldata[-1]["Purpose"]

        if cdata.get("CAS") == "n/a":
            cdata.pop("CAS")

        if cdata.get('MaxConc_in_fluid'):
            assert cdata['MaxConc_in_fluid'][-1] == "%", cdata
            cdata['MaxConc_in_fluid'] = float(cdata['MaxConc_in_fluid'][:-1])

        if cdata.get('MaxConc_in_additive') == "Trade Secret":
            print "TRADE SECRET", API
        elif cdata.get('MaxConc_in_additive'):
            mconc = re.match("(?:([\d\.]+)\s*-\s*)?(<\s*)?([\d\.]+)%?$", cdata['MaxConc_in_additive'])
            if mconc:
                if mconc.group(1):
                    cdata['MinConc_in_additive'] = float(mconc.group(1))
                if mconc.group(2):
                    cdata['MinConc_in_additive'] = 0.0
                cdata['MaxConc_in_additive'] = float(mconc.group(3))
            else:
                assert cdata['MaxConc_in_additive'] == "-", cdata

        # fix missing columns
        if "Ingredients" not in cdata:
            if cdata.get("Trade Name") == "Fresh Water":
                cdata["Ingredients"] = cdata["Trade Name"]
            elif cdata.get("Supplier") == "Halliburton":
                cdata["Ingredients"] = "blank"

        assert "Trade Name" in cdata and "Ingredients" in cdata, cdata
        ldata.append(cdata)

    scraperwiki.sqlite.save(["API", "Trade Name", "Ingredients"], ldata, "fluidcomp", verbose=0)
    scraperwiki.sqlite.save(["API"], data, "wellinfo", verbose=0)  # this table is used to determin that it is done

Main()