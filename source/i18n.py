"""Small runtime translation layer for SlothCAD's English/Hungarian UI."""
import re
from platform_support import settings as app_settings

_LANGUAGE='en'

HU={
'Finish':'Befejezés','Circular':'Körkörös',
'Set the size in mm, then click a corner where sketch curves meet. Repeat for more corners; undo restores each edit.':'Add meg a méretet mm-ben, majd kattints a vázlatgörbék találkozási sarkára. További sarkokhoz ismételd meg; a Visszavonás minden módosítást visszaállít.',
'click model edges to toggle selection; click a vertex to select its incident edges':'Kattints az élekre a kijelölés váltásához, vagy egy csúcsra az összes csatlakozó él kijelöléséhez.',
'Click a corner where two sketch curves meet.':'Kattints két vázlatgörbe találkozási sarkára.',
'Click model edges to toggle selection; click a vertex to select its incident edges':'Kattints az élekre a kijelölés váltásához, vagy egy csúcsra az összes csatlakozó él kijelöléséhez.',
'Corner size must be greater than zero.':'A sarok méretének nullánál nagyobbnak kell lennie.',
'Corner size is too large for the adjacent edges.':'A sarok mérete túl nagy a szomszédos élekhez.',
'Choose a corner with two non-collinear edges.':'Válassz olyan sarkot, amelynek két éle nem esik egy egyenesre.',
# Menus and global actions
'File':'Fájl','Edit':'Szerkesztés','Settings':'Beállítások','Help':'Súgó','Language':'Nyelv',
'English':'Angol','Hungarian':'Magyar','New':'Új','Open':'Megnyitás','Save':'Mentés','Save as':'Mentés másként',
'Export STEP / STL':'STEP / STL exportálása','Example part':'Példa alkatrész','Undo':'Visszavonás','Redo':'Újraalkalmazás',
'Undo · Ctrl+Z':'Visszavonás · Ctrl+Z','Redo · Ctrl+Shift+Z':'Újraalkalmazás · Ctrl+Shift+Z',
'Appearance…':'Megjelenés…','Default body appearance…':'Alapértelmezett testmegjelenés…',
'Graphics diagnostics':'Grafikai diagnosztika','Sketch shortcuts…':'Vázlat gyorsbillentyűk…','Controls / scope':'Vezérlés / lehetőségek',
'Graphics issues':'Grafikai problémák','Operation could not be completed':'A művelet nem hajtható végre',
'Unsaved project':'Nem mentett projekt','Unapplied changes':'Nem alkalmazott módosítások',
# Ribbon / modes
'CREATE':'LÉTREHOZÁS','MODIFY':'MÓDOSÍTÁS','HISTORY':'ELŐZMÉNYEK','SELECT':'KIJELÖLÉS','DRAW':'RAJZ','TRANSFORM':'ÁTALAKÍTÁS','SKETCH':'VÁZLAT','MODE':'MÓD',
'SOLID':'TEST','SELECT PLANE':'SÍK KIJELÖLÉSE','EXTRUDE':'KIHÚZÁS','SELECT EDGES':'ÉLEK KIJELÖLÉSE','EXTRUDE SELECT':'KIHÚZÁSI PROFILOK',
'Create sketch':'Vázlat létrehozása','Extrude':'Kihúzás','Fillet':'Lekerekítés','Chamfer':'Letörés','Delete feature':'Művelet törlése',
'Select':'Kijelölés','Line':'Vonal','Arc':'Ív','Rectangle':'Téglalap','Circle':'Kör','Trim':'Levágás','Guide':'Segédgeometria',
'Mirror':'Tükrözés','Circular pattern':'Körkiosztás','Rectangular pattern':'Téglalap alakú kiosztás','Finish sketch':'Vázlat befejezése','Cancel sketch':'Vázlat megszakítása',
'More sketch drawing tools':'További vázlateszközök',
# Draw palette
'Corner rectangle':'Sarokponti téglalap','Center rectangle':'Középpontos téglalap','3-point rectangle':'3 pontos téglalap',
'Center-radius circle':'Kör középponttal és sugárral','3-point circle':'3 pontos kör','3-point arc':'3 pontos ív','Center arc':'Középpontos ív',
'Polygon':'Sokszög','Triangle':'Háromszög','Pentagon':'Ötszög','Hexagon':'Hatszög','Octagon':'Nyolcszög','Regular polygon…':'Szabályos sokszög…',
'Ellipse':'Ellipszis','Slot':'Horony','Center-to-center slot':'Középpontok közötti horony','Spline':'Spline','Control-point spline':'Vezérlőpontos spline',
'Conic curve':'Kúpszelet','Point':'Pont','Text…':'Szöveg…','Regular polygon':'Szabályos sokszög','Number of sides':'Oldalak száma','Sketch text':'Vázlatszöveg','Text':'Szöveg','Height (mm)':'Magasság (mm)',
# Panels / forms
'BODIES & SKETCHES':'TESTEK ÉS VÁZLATOK','Bodies':'Testek','Sketches':'Vázlatok','Body':'Test','Sketch':'Vázlat','FEATURES  →':'MŰVELETEK  →',
'Check to show · Double-click sketch to edit':'Jelöld be a megjelenítéshez · Dupla kattintás a vázlat szerkesztéséhez',
'Sketch settings':'Vázlatbeállítások','Geometry list':'Geometrialista','Precise input':'Pontos bevitel','Construction guide':'Segédvonal',
'Grid spacing':'Rácsköz','Snap to grid and geometry':'Illesztés a rácshoz és geometriához','Delete selected geometry':'Kijelölt geometria törlése',
'Apply geometry edit':'Geometriamódosítás alkalmazása','Add geometry':'Geometria hozzáadása','Name':'Név','Active':'Aktív','Suppressed':'Letiltva',
'Feature parameters':'Művelet paraméterei','Feature details':'Művelet részletei','Direction & details':'Irány és részletek','Legacy extrusion details':'Régi kihúzás részletei',
'Depth':'Mélység','Extrusion depth':'Kihúzás mélysége','Operation':'Művelet','Direction':'Irány','Start offset':'Kezdő eltolás','Start offset (mm)':'Kezdő eltolás (mm)',
'Selection':'Kijelölés','Edges':'Élek','Fillet radius':'Lekerekítés sugara','Chamfer distance':'Letörés távolsága',
'Apply extrusion':'Kihúzás alkalmazása','Apply feature':'Művelet alkalmazása','Preview':'Előnézet','Cancel':'Mégse','Clear':'Törlés','Select sources':'Források kijelölése',
'Preview active · Apply to keep it':'Előnézet aktív · Az Alkalmazás gombbal véglegesíthető','Apply is always available here; Preview is optional.':'Az Alkalmazás mindig elérhető itt; az Előnézet opcionális.',
'Preview only · Apply to keep this result':'Csak előnézet · Az Alkalmazás gombbal tartható meg','Parameters changed · click Preview to update':'A paraméterek megváltoztak · kattints az Előnézetre a frissítéshez',
'Construction guides: snap and mirror references; never extruded.':'Segédgeometria: illesztési és tükrözési referencia; soha nem kerül kihúzásra.',
'Normal sketch geometry.':'Normál vázlatgeometria.','Width':'Szélesség','Height':'Magasság','Radius':'Sugár','Center':'Középpont','Major axis point':'Nagytengely pontja','Minor radius':'Kistengely félhossza',
'First center':'Első középpont','Second center':'Második középpont','Start':'Kezdőpont','Through':'Átmenő pont','End':'Végpont','Control':'Vezérlőpont',
'Center X':'Középpont X','Center Y':'Középpont Y','Origin X':'Origó X','Origin Y':'Origó Y','Origin Z':'Origó Z','X spacing':'X osztásköz','Y spacing':'Y osztásköz',
'Columns':'Oszlopok száma','Rows':'Sorok száma','New copies':'Új másolatok','Guide':'Segédgeometria',
# Pattern workflow
'Pattern workflow: choose source geometry, set the pattern reference/spacing, then create the copies.':'Kiosztás menete: válaszd ki a forrásgeometriát, add meg a referenciát/távolságot, majd hozd létre a másolatokat.',
'Choose source geometry':'Forrásgeometria kiválasztása','Select source geometry':'Forrásgeometria kijelölése','Select the center point':'Középpont kijelölése','Select the guide line':'Vezetővonal kijelölése',
'Click the workspace to place the center, or type the X / Y values below.':'Kattints a munkaterületre a középpont megadásához, vagy írd be lent az X / Y értékeket.',
'Click sketch entities in the viewport or select them in the list.':'Kattints a vázlatelemekre a nézetben, vagy jelöld ki őket a listában.',
'Click a straight sketch line in the viewport, or choose one from the Guide field.':'Kattints egy egyenes vázlatvonalra a nézetben, vagy válaszd ki a Vezetővonal mezőből.',
'Choose guide line in workspace':'Vezetővonal kiválasztása a munkaterületen','Choose center point in workspace':'Középpont kiválasztása a munkaterületen',
'Create mirrored copies':'Tükrözött másolatok létrehozása','Create circular pattern':'Körkiosztás létrehozása','Create rectangular pattern':'Téglalap-kiosztás létrehozása',
'Line mirror':'Vonalra tükrözés','Choose a straight line…':'Válassz egy egyenes vonalat…','No guide line selected yet':'Még nincs vezetővonal kijelölve','No center point selected yet':'Még nincs középpont kijelölve',
'5 copies + original = 6 equal positions.':'5 másolat + eredeti = 6 egyenletes pozíció.','The original is the first grid position; copies extend by the X/Y spacing values.':'Az eredeti az első rácspozíció; a másolatok az X/Y osztásköz szerint készülnek.',
# Extrude / edge selection
'Selected faces/profiles glow in the viewport; click one again to remove it.':'A kijelölt felületek/profilok kiemelve maradnak; ismételt kattintással eltávolíthatók.',
'Auto checks overlap when applying and asks Join or Cut when needed.':'Az Automatikus mód alkalmazáskor ellenőrzi az átfedést, és szükség esetén Egyesítés vagy Kivágás között kér választást.',
'Extrusion crosses an existing body':'A kihúzás meglévő testet keresztez','This extrusion intersects existing solid material. What should SlothCAD do?':'A kihúzás meglévő testtel fed át. Mit tegyen a SlothCAD?',
'Join':'Egyesítés','Cut':'Kivágás','Select one or more closed sketch profiles and/or planar body faces. Selected sources stay highlighted. Every selected source will use the same extrusion depth and operation.':'Jelölj ki egy vagy több zárt vázlatprofilt és/vagy sík testfelületet. A kijelölt források kiemelve maradnak, és mind ugyanazt a kihúzási mélységet és műveletet használják.',
'Cancel extrusion':'Kihúzás megszakítása','Maximum for selected edges: select one or more edges first.':'Maximum a kijelölt élekhez: előbb jelölj ki legalább egy élt.',
'Maximum for selected edges: calculating after selection…':'Maximum a kijelölt élekhez: számítás folyamatban…',
# Appearance / viewport
'Settings · Appearance':'Beállítások · Megjelenés','SLOTHCAD  /  APPEARANCE':'SLOTHCAD  /  MEGJELENÉS','Light':'Világos','Dark':'Sötét',
'Ivory or slate. Your choice is remembered for every project and the next launch.':'Világos vagy sötét téma. A választást a program minden projekthez és a következő indításkor is megjegyzi.',
'Default body appearance':'Alapértelmezett testmegjelenés','Finish':'Felület','Color':'Szín','Choose body color':'Testszín kiválasztása',
'matte':'matt','metallic':'fémes','wood':'fa','Camera orientation':'Kamera tájolása','Fit':'Nézetbe illesztés','Grid':'Rács','Axes':'Tengelyek','Smooth edges':'Élsimítás',
'Fit all visible objects':'Minden látható objektum nézetbe illesztése','Iso':'Izometrikus','Top':'Felülnézet','Front':'Elölnézet','Right':'Jobb oldali nézet',
# History
'Show model at this point':'Modell megjelenítése ennél a pontnál','Edit this feature':'Művelet szerkesztése','Revert project to this point…':'Projekt visszaállítása eddig…',
'Revert feature history':'Művelettörténet visszaállítása','Return to latest model':'Vissza a legújabb modellhez','History preview':'Előzmény előnézete',
'Click to edit extrusion':'Kattints a kihúzás szerkesztéséhez','Click to edit parameters':'Kattints a paraméterek szerkesztéséhez','Double-click to edit sketch':'Dupla kattintás a vázlat szerkesztéséhez',
'Active':'Aktív','Suppressed':'Letiltva','visible':'látható','hidden':'rejtett','closed profiles':'zárt profil',
# File dialogs / status
'Open project':'Projekt megnyitása','Save project':'Projekt mentése','Export solid':'Test exportálása','SlothCAD projects (*.fcad)':'SlothCAD projektek (*.fcad)',
'Preparing viewport…':'Nézet előkészítése…','Building preview…':'Előnézet készítése…','Opening project…':'Projekt megnyitása…','Opening example…':'Példa megnyitása…','Rebuilding model…':'Modell újraépítése…','Undoing change…':'Módosítás visszavonása…','Redoing change…':'Módosítás újraalkalmazása…','Reverting feature history…':'Művelettörténet visszaállítása…','Checking extrusion overlap…':'Kihúzás átfedésének ellenőrzése…',
'Preview only. Orbit to inspect; Apply commits, Cancel restores the model.':'Csak előnézet. Forgasd a nézetet az ellenőrzéshez; az Alkalmazás véglegesít, a Mégse visszaállítja a modellt.',
'A CAD operation is still finishing; the window is responsive and will be ready shortly.':'Egy CAD-művelet még fut; az ablak működik, és rövidesen használható lesz.',
'Finish your sketch or Apply / Cancel current feature changes before saving.':'Mentés előtt fejezd be a vázlatot, vagy Alkalmazd / vond vissza az aktuális művelet módosításait.',
'Finish your sketch or Apply / Cancel current changes before exporting.':'Exportálás előtt fejezd be a vázlatot, vagy Alkalmazd / vond vissza az aktuális módosításokat.',
# Guidance
'Click sketch geometry to edit its dimensions. Use L / R / C / A to draw.':'Kattints a vázlatgeometriára a méretek szerkesztéséhez. Rajzolás: L / R / C / A.',
'Click edges to trim between intersections.':'Kattints az élekre a metszéspontok közötti vágáshoz.','Click to draw, or type a size after placing the first point. Tab switches dimensions.':'Kattints a rajzoláshoz, vagy az első pont után írj be méretet. A Tab vált a méretek között.',
'Click center, major-axis point, then minor radius.':'Kattints a középpontra, a nagytengely pontjára, majd add meg a kissugarat.','Click both slot centers, then set the width.':'Kattints a horony két középpontjára, majd add meg a szélességet.',
'Click control points; press Enter to finish the spline.':'Kattints a vezérlőpontokra; Enterrel fejezd be a spline-t.','Click start, end, then the control point.':'Kattints a kezdőpontra, végpontra, majd a vezérlőpontra.',
'Click once to place a sketch reference point.':'Kattints egyszer egy vázlat-referenciapont elhelyezéséhez.','Click once to place the text outlines.':'Kattints egyszer a szöveg körvonalainak elhelyezéséhez.',
'Click the center, then a corner.':'Kattints a középpontra, majd egy sarokra.','Click two points for the first edge, then a third point for width.':'Kattints két pontra az első élhez, majd egy harmadik pontra a szélességhez.',
'Click three points on the circle.':'Kattints három pontra a körön.','Click center, start, then end direction.':'Kattints a középpontra, a kezdőpontra, majd a végirányra.',
'Select one of the colored planes in the workspace, or click a planar face on the body.':'Válassz egy színes síkot a munkaterületen, vagy kattints a test egy sík felületére.',
'Origin planes pass through world 0,0,0. A face sketch aligns to the selected face.':'Az alapsíkok a világ 0,0,0 pontján haladnak át. A felületre készített vázlat a kijelölt felülethez igazodik.',
# Workspace overlays
'MODEL · one workspace':'MODELL · egy munkaterület','CREATE SKETCH · select an origin plane or planar body face':'VÁZLAT LÉTREHOZÁSA · válassz alapsíkot vagy sík testfelületet',
'EXTRUDE · select one or more sketch profiles or planar faces':'KIHÚZÁS · jelölj ki egy vagy több vázlatprofilt vagy sík felületet','EDGE SELECT · click one or more edges':'ÉLKIJELÖLÉS · kattints egy vagy több élre',
'Left drag: orbit   Right drag: pan   Wheel: zoom':'Bal húzás: forgatás   Jobb húzás: pásztázás   Görgő: nagyítás',
'Blue: XY   Green: XZ   Orange: YZ   ·   Use plane buttons if a plane is edge-on':'Kék: XY   Zöld: XZ   Narancs: YZ   ·   Ha egy sík élével látszik, használd a síkgombokat',
'Click profiles/faces to toggle selection · all selected sources use the same depth':'Kattints profilokra/felületekre a kijelölés váltásához · minden forrás ugyanazt a mélységet használja',
'Click a face/profile to add or remove it · drag to orbit · all selected sources extrude together':'Kattints felületre/profilra a hozzáadáshoz vagy eltávolításhoz · húzás: forgatás · minden kijelölt forrás együtt kerül kihúzásra',
'Click edges to toggle selection · select several, then Apply in the right panel':'Kattints az élekre a kijelölés váltásához · jelölj ki többet, majd Alkalmazás a jobb panelen',
'Type: exact size · Tab: next field · Enter: place · L/R/C/A: draw · T: trim · X: guides · Esc: cancel':'Gépelés: pontos méret · Tab: következő mező · Enter: elhelyezés · L/R/C/A: rajz · T: vágás · X: segéd · Esc: mégse',
'Arc: click the start point':'Ív: kattints a kezdőpontra','Arc: click the end point':'Ív: kattints a végpontra','Arc: click a bend point away from the chord':'Ív: kattints egy hajlítási pontra a húrtól távol',
'Ellipse: click center':'Ellipszis: kattints a középpontra','Ellipse: click the end of the major axis (it reaches the same distance on both sides)':'Ellipszis: kattints a nagytengely végpontjára (a középpont mindkét oldalán ugyanolyan messze ér)','Ellipse: click minor radius':'Ellipszis: add meg a kissugarat',
'Slot: click first center':'Horony: kattints az első középpontra','Slot: click second center':'Horony: kattints a második középpontra','Slot: click to set width':'Horony: kattints a szélesség megadásához',
'Spline: click control points · Enter finishes · Esc cancels':'Spline: kattints vezérlőpontokra · Enter: befejezés · Esc: mégse',
'SELECT SOURCES':'FORRÁSOK KIJELÖLÉSE','SELECT GUIDE LINE':'VEZETŐVONAL KIJELÖLÉSE','SELECT CENTER POINT':'KÖZÉPPONT KIJELÖLÉSE',
'Selecting source geometry · click entities in the viewport or in the list on the right':'Forrásgeometria kijelölése · kattints elemekre a nézetben vagy a jobb oldali listában',
'Selecting the guide line · click a straight sketch line or choose one in the right panel':'Vezetővonal kijelölése · kattints egyenes vázlatvonalra vagy válassz a jobb panelen',
'Selecting the center point · click the workspace or enter X/Y in the right panel':'Középpont kijelölése · kattints a munkaterületre vagy add meg az X/Y értéket a jobb panelen',
'Current drawing canceled.':'Az aktuális rajzolás megszakítva.','Enter a valid dimension; lengths must be greater than zero.':'Adj meg érvényes méretet; a hosszúságoknak nullánál nagyobbnak kell lenniük.',
'Place at least two spline control points before pressing Enter.':'Enter előtt helyezz el legalább két spline vezérlőpontot.',
# Snapping / picking
'free':'szabad','grid':'rács','intersection':'metszéspont','endpoint':'végpont','edge':'él','vertex / center':'csúcs / középpont',
'Click an edge to toggle it; multiple edges can be selected.':'Kattints egy élre a kijelölés váltásához; több él is kijelölhető.',
'Choose a straight sketch line as the mirror guide.':'Válassz egy egyenes vázlatvonalat tükrözési vezetőként.',
'Click to sketch on this origin plane':'Kattints vázlat létrehozásához ezen az alapsíkon','Click to add/remove this planar face from the extrusion':'Kattints a sík felület hozzáadásához/eltávolításához a kihúzásból','Click to add/remove this closed sketch profile from the extrusion':'Kattints a zárt vázlatprofil hozzáadásához/eltávolításához a kihúzásból','Choose a planar face; this face is curved':'Válassz sík felületet; ez a felület görbült','Click this planar face':'Kattints erre a sík felületre','Click this closed sketch profile':'Kattints erre a zárt vázlatprofilra',
# Common internal display values
'auto':'automatikus','add':'hozzáadás','cut':'kivágás','intersect':'metszet','one side':'egy irány','symmetric':'szimmetrikus','vertical':'függőleges','top':'felső','bottom':'alsó','all':'összes',
'face':'felület','profile':'profil','sources':'forrás','source':'forrás','entities':'elem','item':'elem','selected':'kijelölve','edge(s)':'él',
# Errors / validation surfaced to users
'Select a face or sketch profile to extrude.':'Jelölj ki egy felületet vagy vázlatprofilt a kihúzáshoz.','Select at least one face or sketch profile to extrude.':'Jelölj ki legalább egy felületet vagy vázlatprofilt a kihúzáshoz.',
'Invalid extrusion source list.':'Érvénytelen kihúzási forráslista.','Create a body first.':'Előbb hozz létre egy testet.','Select at least one edge.':'Jelölj ki legalább egy élt.',
'Unknown edge feature type.':'Ismeretlen élművelet.','A selected edge no longer exists.':'Egy kijelölt él már nem létezik.','A selected edge changed too much after an earlier edit. Re-select the edge(s).':'Egy kijelölt él túl sokat változott egy korábbi módosítás után. Jelöld ki újra az él(eke)t.',
'Unsupported project format or version.':'Nem támogatott projektformátum vagy verzió.','Invalid project data.':'Érvénytelen projektadatok.','Create a solid before exporting.':'Exportálás előtt hozz létre szilárd testet.','Choose a .step, .stp or .stl filename.':'Adj meg .step, .stp vagy .stl fájlnevet.',
'Depth cannot be zero.':'A mélység nem lehet nulla.','Choose one side or symmetric extrusion.':'Válassz egyirányú vagy szimmetrikus kihúzást.','Unknown operation.':'Ismeretlen művelet.','Operation produced an empty or invalid solid.':'A művelet üres vagy érvénytelen testet eredményezett.',
'A negative extrusion needs an existing body.':'Negatív kihúzáshoz meglévő test szükséges.','The first solid feature must add material.':'Az első testműveletnek anyagot kell hozzáadnia.','The source sketch is missing, suppressed, or later in history.':'A forrásvázlat hiányzik, le van tiltva, vagy később található az előzményekben.',
'The cut does not intersect a body. Check its direction, start offset and depth.':'A kivágás nem metsz testet. Ellenőrizd az irányt, a kezdő eltolást és a mélységet.','The selected sketch region changed. Select its profile again.':'A kijelölt vázlatrégió megváltozott. Jelöld ki újra a profilját.',
'A sketch frame must contain 3D vectors.':'A vázlatsíknak 3D vektorokat kell tartalmaznia.','Invalid sketch axes.':'Érvénytelen vázlattengelyek.','Sketch axes must be perpendicular.':'A vázlattengelyeknek merőlegesnek kell lenniük.',
'Choose a planar face. Curved faces do not have one sketch plane.':'Válassz sík felületet. A görbült felületekhez nem tartozik egyetlen vázlatsík.','The supporting body no longer exists.':'A vázlatot hordozó test már nem létezik.','The referenced planar face no longer exists.':'A hivatkozott sík felület már nem létezik.',
'Arc points must not lie on a straight line.':'Az ív pontjai nem lehetnek egy egyenesen.','Major radius must be greater than zero.':'A nagytengely félhosszának nullánál nagyobbnak kell lennie.','Polygon sides must be between 3 and 128.':'A sokszög oldalszámának 3 és 128 között kell lennie.','Polygon radius must be greater than zero.':'A sokszög sugarának nullánál nagyobbnak kell lennie.',
'Spline needs at least two control points.':'A spline-hoz legalább két vezérlőpont szükséges.','Text cannot be empty.':'A szöveg nem lehet üres.','Could not create text with an installed system font.':'A szöveg nem hozható létre a telepített rendszerbetűtípusokkal.','Text did not produce any sketch outlines.':'A szöveg nem hozott létre vázlatkörvonalat.',
'Select a closed sketch profile. Connect line/arc endpoints using snapping.':'Jelölj ki zárt vázlatprofilt. Az illesztéssel csatlakoztasd a vonal-/ívvégpontokat.','Sketch profile is degenerate or self-intersecting.':'A vázlatprofil degenerált vagy önmagát metszi.',
'Select a straight sketch line as the mirror guide.':'Válassz egy egyenes vázlatvonalat tükrözési vezetőként.','The mirror guide must have a nonzero length.':'A tükrözési vezetővonal hossza nem lehet nulla.','Choose 1–100 new copies.':'Válassz 1–100 új másolatot.','Columns must be between 1 and 100.':'Az oszlopszámnak 1 és 100 között kell lennie.','Rows must be between 1 and 100.':'A sorok számának 1 és 100 között kell lennie.',
'X spacing must be nonzero when using multiple columns.':'Több oszlop esetén az X osztásköz nem lehet nulla.','Y spacing must be nonzero when using multiple rows.':'Több sor esetén az Y osztásköz nem lehet nulla.','A line needs two different endpoints.':'Egy vonalhoz két különböző végpont szükséges.','Polygon needs at least three points.':'A sokszöghöz legalább három pont szükséges.','Slot center points must be different points.':'A horony középpontjainak különböző pontoknak kell lenniük.','Construction guides cannot be extruded. Change the guide to normal geometry first.':'A segédgeometria nem húzható ki. Előbb alakítsd normál geometriává.','Disconnected profile.':'Nem összefüggő profil.','Click a sketch edge to trim.':'Kattints egy vázlatélre a vágáshoz.','This sketch item has no trimmable edge.':'Ennek a vázlatelemnek nincs vágható éle.',
}


HU.update({'DRAW  ▾':'RAJZ  ▾','Draw tools  ▾':'Rajzeszközök  ▾','Close':'Bezárás',
'Exporting STEP…':'STEP exportálása…','Exporting STL…':'STL exportálása…','Export STEP…':'STEP exportálása…','Export STL…':'STL exportálása…','Export STEP':'STEP exportálása','Export STL':'STL exportálása',
'STEP solid (*.step *.stp)':'STEP test (*.step *.stp)','STL mesh (*.stl)':'STL háló (*.stl)',
'Measure':'Mérés','Measure · M':'Mérés · M','MEASURE':'MÉRÉS','INSPECT':'ELLENŐRZÉS','Corner':'Csúcs','Point':'Pont','Edge':'Él','Face':'Felület',
'Sketch point':'Vázlatpont','Sketch edge':'Vázlatél','Sketch face':'Vázlatfelület','Area':'Terület','Diameter':'Átmérő','Shortest distance':'Legrövidebb távolság',
'Preparing measurement geometry…':'Mérési geometria előkészítése…','Measuring geometry…':'Geometria mérése…',
'Clear measurement':'Mérés törlése','Done measuring':'Mérés befejezése',
'Click any point, corner, edge or face. Select a second object for the shortest distance between them. A third click starts a new measurement.':'Kattints egy pontra, csúcsra, élre vagy felületre. A második elem kijelölése a köztük lévő legrövidebb távolságot adja meg. A harmadik kattintás új mérést kezd.',
'Size (mm)':'Méret (mm)','Polygon settings':'Sokszög beállításai','Sizing mode':'Méretezési mód','Vertex radius (inscribed)':'Csúcsok sugara (körbe írt)',
'Edge radius (circumscribed)':'Oldalak sugara (kör köré írt)','Vertex radius':'Csúcsok sugara','Edge radius':'Oldalak sugara',
'Vertex radius (mm)':'Csúcsok sugara (mm)','Edge radius (mm)':'Oldalak sugara (mm)','Edge length (mm)':'Oldalhossz (mm)','Use exact size':'Pontos méret használata',
'Preparing sketch…':'Vázlat előkészítése…','Preparing sketch regions…':'Vázlatprofilok előkészítése…','Preparing pattern…':'Kiosztás előkészítése…',
'Trimming sketch…':'Vázlat levágása…','Building text outlines…':'Szöveg körvonalainak létrehozása…',
'Click points; click the first point to close the spline, or press Enter for an open curve.':'Kattints a pontokra, majd az első pontra a görbe lezárásához. Az Enter nyitott görbeként fejezi be.',
'Spline: click points · click the first point to close · Enter finishes open · Esc cancels':'Spline: pontok kijelölése · első pont: lezárás · Enter: nyitott görbe · Esc: mégse',
'Set the sides and sizing mode, then click the center (or first corner in Edge length mode). Click again to set orientation. Type a size while drawing, or enable Use exact size.':'Állítsd be az oldalak számát és a méretezési módot, majd kattints a középpontra (Oldalhossz módban az első csúcsra). A következő kattintás az irányt adja meg. Rajzolás közben méretet is beírhatsz, vagy bekapcsolhatod a Pontos méret használata opciót.'})
HU.update({
'OK':'OK','display':'megjelenítés','Language setting saved.':'A nyelvi beállítás elmentve.',
'Graphics issue · Click to view details':'Grafikai probléma · Kattints a részletekhez',
'Smooth edges · GPU supersampling (16× on small viewports, 4× otherwise); falls back to MSAA when needed':'Élsimítás · GPU túlmintavételezés (kis nézeteknél 16×, egyébként 4×); szükség esetén MSAA',
'The GPU solid renderer encountered an issue. Software drawing is keeping your model visible.':'A GPU-s testmegjelenítő hibát észlelt. A szoftveres rajzolás továbbra is láthatóvá teszi a modellt.',
'No graphics issues detected.':'Nem észlelhető grafikai probléma.',
'Toggle visibility; double-click to change this body’s color/finish.':'Láthatóság váltása; dupla kattintással módosítható a test színe/felülete.',
'Toggle sketch visibility. Double-click its name to edit. Consumed sketches are initially hidden.':'Vázlat láthatóságának váltása. A névre duplán kattintva szerkeszthető. A felhasznált vázlatok kezdetben rejtve vannak.',
'Click: show model at this history point':'Kattintás: modell megjelenítése ezen az előzményponton','Double-click: edit this feature':'Dupla kattintás: művelet szerkesztése','Right-click: history actions':'Jobb kattintás: előzményműveletek',
'Save this project before continuing?':'Mented a projektet a folytatás előtt?','Discard the current unapplied changes?':'Elveted az aktuális, még nem alkalmazott módosításokat?',
})

_shortcuts_en="""Click the workspace, then use (Fusion 360 keys):
Sketch: L — Line    R — Rectangle    C — Circle    A — Arc    D — Dimension
O — Offset    T — Trim    P — Project    X — Construction    V — Select
E — Finish the sketch and extrude
Delete — Remove the selected sketch geometry or dimension
Model: E — Extrude    F — Fillet    Q — Press pull    H — Hole    M — Move/Copy
I — Measure    F6 — Fit all    Z — Zoom to selection
Ctrl+Z — Undo    Ctrl+Y / Ctrl+Shift+Z — Redo

While drawing: type a dimension, Tab / Shift+Tab to switch fields, Enter to place, Esc to cancel.

Guides snap like normal geometry but never create extrusion profiles. Symmetric extrusion uses total depth."""
_shortcuts_hu="""Kattints a munkaterületre, majd használd (Fusion 360 billentyűk):
Vázlat: L — Vonal    R — Téglalap    C — Kör    A — Ív    D — Méret
O — Eltolás    T — Vágás    P — Vetítés    X — Segédgeometria    V — Kijelölés
E — Vázlat befejezése és kihúzás
Delete — A kijelölt vázlatgeometria vagy méret törlése
Modell: E — Kihúzás    F — Lekerekítés    Q — Nyomás/húzás    H — Furat    M — Mozgatás/másolás
I — Mérés    F6 — Teljes nézet    Z — Nagyítás a kijelölésre
Ctrl+Z — Visszavonás    Ctrl+Y / Ctrl+Shift+Z — Újra

Rajzolás közben: írj be méretet, Tab / Shift+Tab vált a mezők között, Enter elhelyez, Esc megszakít.

A segédgeometria ugyanúgy illeszkedik, mint a normál geometria, de nem hoz létre kihúzható profilt. A szimmetrikus kihúzás teljes mélységet használ."""
HU[_shortcuts_en]=_shortcuts_hu

_scope_en="""Create sketch: choose a colored origin plane or a planar body face.
Sketch tools: click two points for a line, rectangle or circle.
Arc: click start, end, then a bend point. Line continues until Esc or another tool.
Grid, vertices/centers and edges snap. Numeric input can use any size.
Finish sketch, then Extrude: click inside one or more closed profiles or planar body faces.
Enter positive/negative depth and Add/Cut/Intersect, then Apply.

Model: left drag orbit, right/middle drag pan; wheel zoom; double-click fit.
Sketch: right/middle drag pan; wheel zoom; Esc cancels drawing.
Click a feature in the history to preview that point; double-click it to edit.

Curved-face sketching and assemblies are not included.
Face supports use geometric matching; ambiguous references stop rebuilding."""
_scope_hu="""Vázlat létrehozása: válassz egy színes alapsíkot vagy a test egy sík felületét.
Vázlateszközök: vonalhoz, téglalaphoz vagy körhöz kattints a szükséges pontokra.
Ív: kattints a kezdőpontra, végpontra, majd egy hajlítási pontra. A vonal addig folytatódik, amíg Esc-et vagy másik eszközt nem választasz.
A rács, csúcsok/középpontok és élek illeszkednek. Számbevitellel tetszőleges méret megadható.
Fejezd be a vázlatot, majd Kihúzás: kattints egy vagy több zárt profilba vagy sík testfelületre.
Adj meg pozitív/negatív mélységet és Hozzáadás/Kivágás/Metszet műveletet, majd Alkalmazás.

Modell: bal húzás forgat, jobb/középső húzás pásztáz, görgő nagyít, dupla kattintás nézetbe illeszt.
Vázlat: jobb/középső húzás pásztáz, görgő nagyít, Esc megszakítja a rajzolást.
Kattints egy műveletre az előzményekben az adott állapot előnézetéhez; dupla kattintással szerkeszthető.

Görbült felületre vázlatolás és összeállítások jelenleg nincsenek benne.
A felülettámaszok geometriai illesztést használnak; kétértelmű hivatkozás esetén az újraépítés leáll."""
HU[_scope_en]=_scope_hu

HU.update({
'Sketch shortcuts':'Vázlat gyorsbillentyűk','Sketch on face':'Vázlat felületen','Planar face':'Sík felület','Extrude a profile':'Profil kihúzása',
'Double-click this sketch in the left panel to edit it.':'A szerkesztéshez kattints duplán erre a vázlatra a bal oldali panelen.',
'Create sketch to start on an origin plane or body face. Finish the sketch, then use Extrude to select a profile. Extrude also works directly on planar body faces.':'A kezdéshez hozz létre vázlatot egy alapsíkon vagy testfelületen. Fejezd be a vázlatot, majd a Kihúzás eszközzel válassz profilt. A Kihúzás közvetlenül sík testfelületeken is működik.',
'Draw or add at least one sketch entity before finishing.':'Befejezés előtt rajzolj vagy adj hozzá legalább egy vázlatelemet.','Enter a sketch name.':'Adj meg vázlatnevet.','Extrude selection':'Kihúzás kijelölése','Enter a feature name.':'Adj meg műveletnevet.',
'Preparing geometry before this feature…':'A művelet előtti geometria előkészítése…','Finding maximum':'Maximum keresése','Create a body before using':'Használat előtt hozz létre testet',
'XY plane · normal Z':'XY sík · normál Z','XZ plane · normal Y':'XZ sík · normál Y','YZ plane · normal X':'YZ sík · normál X','Select a guide line.':'Jelölj ki egy vezetővonalat.','Select a middle point.':'Jelölj ki egy középpontot.',
'Selecting source geometry. Click geometry to toggle selection.':'Forrásgeometria kijelölése. Kattints a geometriára a kijelölés váltásához.','Selecting the guide line. Click a straight sketch line for the mirror guide.':'Vezetővonal kijelölése. Kattints egy egyenes vázlatvonalra a tükrözési vezetőhöz.','Selecting the center point. Click the workspace; grid and geometry snapping apply.':'Középpont kijelölése. Kattints a munkaterületre; a rács- és geometriai illesztés működik.',
'STEP solid (*.step);;STL mesh (*.stl)':'STEP test (*.step);;STL háló (*.stl)','Exported':'Exportálva','Unnamed':'Névtelen','Corner':'Sarok','Source:':'Forrás:','Sources:':'Források:','Sketch sources:':'Vázlatforrások:',
'Angle':'Szög','Bend':'Ívmagasság','SELECTED':'KIJELÖLVE','PLANE':'SÍK','SOURCE':'FORRÁS',
'Circle points must not be collinear.':'A kör pontjai nem lehetnek egy egyenesen.','Choose a bend point away from the chord.':'Válassz hajlítási pontot a húrtól távol.','First rectangle edge needs two different points.':'A téglalap első éléhez két különböző pont szükséges.','Third point must be away from the first edge.':'A harmadik pontnak az első éltől távol kell lennie.',
'Choose an end point different from the start.':'Válassz a kezdőponttól eltérő végpontot.','Choose a start point away from the center.':'Válassz a középponttól eltérő kezdőpontot.','Choose an end direction away from the center.':'Válassz a középponttól eltérő végirányt.','Choose a different end angle.':'Válassz másik végszöget.','Choose a major-axis point away from the center.':'Válassz a középponttól eltérő nagytengely-pontot.','Choose a minor radius away from the major axis.':'Válassz a nagytengelytől eltérő kissugarat.','Slot center points must be different.':'A horony középpontjainak különbözniük kell.','Choose a slot width away from the center line.':'Válassz a középvonaltól eltérő horonyszélességet.',
'Backend:':'Megjelenítő:','Solid display fallback: CPU rasterizer (Qt OpenGL composition).':'Testmegjelenítés tartalék módja: CPU raszterező (Qt OpenGL kompozíció).','Plane selector cache builds:':'Sík-kijelölő gyorsítótár építései:','Motion events / applied batches:':'Mozgási események / alkalmazott kötegek:','Device pixel ratio:':'Eszköz pixelaránya:','Triangles:':'Háromszögek:','OpenGL':'OpenGL','CPU software':'CPU szoftver','WARNING: OpenGL driver is software rendering on the CPU.':'FIGYELMEZTETÉS: az OpenGL illesztőprogram szoftveresen, CPU-n renderel.','Mesh uploads:':'Hálófeltöltések:','Solid renderer error:':'Testmegjelenítő hibája:','Median paint submission:':'Medián rajzolási beküldés:','ms (excludes display/driver waits)':'ms (a kijelző/illesztőprogram várakozása nélkül)','No working OpenGL context yet.':'Még nincs működő OpenGL-környezet.','SlothCAD solid renderer error:':'SlothCAD testmegjelenítő hiba:',
'XY · Z normal':'XY · Z normál','XZ · Y normal':'XZ · Y normál','YZ · X normal':'YZ · X normál',
})

HU.update({
'Invalid saved edge reference.':'Érvénytelen mentett élhivatkozás.','Invalid display preferences.':'Érvénytelen megjelenítési beállítások.','Invalid default body appearance.':'Érvénytelen alapértelmezett testmegjelenés.','Invalid body appearances.':'Érvénytelen testmegjelenések.','Invalid visibility preferences.':'Érvénytelen láthatósági beállítások.','Invalid viewport preferences.':'Érvénytelen nézetbeállítások.','Duplicate sketch ID.':'Ismétlődő vázlatazonosító.','Duplicate sketch entity ID.':'Ismétlődő vázlatelem-azonosító.','Unknown feature type.':'Ismeretlen művelettípus.','Unknown extrusion source.':'Ismeretlen kihúzási forrás.','Unknown edge selection.':'Ismeretlen élkijelölés.','No edges match this selection.':'Egy él sem felel meg ennek a kijelölésnek.',
'Entity does not have open endpoints.':'Az elemnek nincsenek nyitott végpontjai.','Unknown sketch entity.':'Ismeretlen vázlatelem.','Unsupported sketch entity.':'Nem támogatott vázlatelem.','Arc points must have two coordinates.':'Az ív pontjainak két koordinátából kell állniuk.','Text position needs two coordinates.':'A szöveg pozíciójához két koordináta szükséges.','Construction status must be true or false.':'A segédgeometria állapotának igaz vagy hamis értéknek kell lennie.','Sketch copies require a rigid 2D transformation.':'A vázlatmásolatokhoz merev 2D transzformáció szükséges.','The pattern center requires two coordinates.':'A kiosztás középpontjához két koordináta szükséges.','Reduce the selection or copy count (limit: 5,000 entities).':'Csökkentsd a kijelölést vagy a másolatok számát (határ: 5 000 elem).','Choose at least two pattern positions.':'Válassz legalább két kiosztási pozíciót.','Reduce the selection or pattern size (limit: 5,000 entities).':'Csökkentsd a kijelölést vagy a kiosztás méretét (határ: 5 000 elem).','Face reference is ambiguous after an earlier edit. Re-select its support.':'A felülethivatkozás egy korábbi módosítás után nem egyértelmű. Jelöld ki újra a vázlatot hordozó felületet.','Slot centers must be different points.':'A horony középpontjainak különböző pontoknak kell lenniük.','Sketch coordinates must be finite pairs.':'A vázlatkoordinátáknak véges számpároknak kell lenniük.','Point needs two coordinates.':'A ponthoz két koordináta szükséges.','An extruded profile entity was removed from its sketch.':'A kihúzott profil egyik eleme eltávolításra került a vázlatból.',
})

HU.update({
'Conic':'Kúpszelet','guide':'segéd','sketch':'vázlat','selection':'kijelölés','fillet':'lekerekítés','chamfer':'letörés',
'Length':'Hossz','Major radius':'Nagytengely félhossza','Center length':'Középpont-távolság','Text height':'Szövegmagasság','Slot width':'Horonyszélesség','Coordinate':'Koordináta','Snap tolerance':'Illesztési tűrés',
})

HU.update({
'Untitled':'Névtelen','not selected':'nincs kijelölve','fillet radius':'lekerekítési sugár','chamfer distance':'letörési távolság','Maximum':'Maximum','for selected edges:':'a kijelölt élekhez:','extrusion source':'kihúzási forrás','STL':'STL','XY':'XY','XZ':'XZ','YZ':'YZ',
})

HU.update({
'click model edges to toggle selection':'kattints a modell éleire a kijelölés váltásához','· Grid:':'· Rács:','SlothCAD graphics:':'SlothCAD grafika:',
})

# Reviewed CAD wording and missing error messages.
HU.update({
'Corner rectangle':'Téglalap két sarokpontból','Spline':'Spline-görbe','Control-point spline':'Spline megadott pontokon át',
'Finish':'Felületi megjelenés','Center length':'Középpontok távolsága','Through':'Közbenső pont',
'A polygon needs at least three distinct vertices.':'A sokszöghöz legalább három különböző csúcs szükséges.',
'Choose XY, XZ, or YZ.':'Válassz az XY, XZ és YZ síkok közül.',
'Extrusion depth cannot be zero.':'A kihúzás mélysége nem lehet nulla.','Unknown sketch profile.':'Ismeretlen vázlatprofil.',
'Edge length':'Élhossz','Unknown language':'Ismeretlen nyelv','Sketch XY':'XY vázlat','Sketch XZ':'XZ vázlat','Sketch YZ':'YZ vázlat',
'Unknown theme':'Ismeretlen téma','Length':'Hossz','Draw tools':'Rajzeszközök',
})

# Phrases used inside formatted/dynamic messages. Longest matches are applied first.
HU.update({'Constraints': 'Kényszerek', 'CONSTRAIN': 'KÉNYSZEREK', 'Coincidence': 'Egybeesés', 'Horizontal': 'Vízszintes', 'Vertical': 'Függőleges', 'Parallel': 'Párhuzamos', 'Perpendicular': 'Merőleges', 'Dimension': 'Méret', 'Equality': 'Egyenlőség', 'Symmetry': 'Szimmetria', 'Tangency': 'Érintőlegesség', 'Apply constraint': 'Kényszer alkalmazása', 'Clear picks': 'Kijelölések törlése', 'Done': 'Kész', 'Driving dimension': 'Vezérlő méret', 'Edit selected dimension': 'Kijelölt méret szerkesztése', 'Remove selected constraint': 'Kijelölt kényszer eltávolítása', 'Type': 'Típus', 'Value': 'Érték', 'Length': 'Hossz', 'Diameter': 'Átmérő', 'Angle to X': 'Szög az X tengelyhez', 'Distance': 'Távolság', 'Horizontal distance': 'Vízszintes távolság', 'Vertical distance': 'Függőleges távolság', 'Pick two points, or a point and a line/circle. Click the origin to anchor a point.': 'Jelölj ki két pontot, vagy egy pontot és egy vonalat/kört. Az origó kijelölésével rögzíthetsz egy pontot.', 'Pick a straight edge.': 'Jelölj ki egy egyenes élt.', 'Pick two straight edges.': 'Jelölj ki két egyenes élt.', 'Pick two straight edges or two circles.': 'Jelölj ki két egyenes élt vagy két kört.', 'Pick two points, then the straight mirror axis.': 'Jelölj ki két pontot, majd az egyenes tükörtengelyt.', 'Pick a straight edge and a circle.': 'Jelölj ki egy egyenes élt és egy kört.', 'Pick an edge/circle, two points, or two straight edges; then choose the dimension.': 'Jelölj ki egy élt/kört, két pontot vagy két egyenes élt, majd válaszd ki a méret típusát.', 'Solving sketch constraints…': 'Vázlatkényszerek megoldása…', 'Conflicting constraints:': 'Ütköző kényszerek:', 'The last valid sketch was kept.': 'Az utolsó érvényes vázlat megmaradt.', 'This edit conflicts with driving constraints. The last valid sketch was kept.': 'A módosítás ütközik a vezérlő kényszerekkel. Az utolsó érvényes vázlat megmaradt.', 'Choose geometry compatible with this constraint.': 'Jelölj ki a kényszerhez megfelelő geometriát.', 'This constraint already exists.': 'Ez a kényszer már létezik.', 'Pick one edge/circle or two points/edges for a dimension.': 'A mérethez jelölj ki egy élt/kört vagy két pontot/élt.', 'Drag points or edges to edit geometry · driving constraints stay enforced · Esc cancels a drag': 'Pontok és élek húzásával szerkeszthetsz · a vezérlő kényszerek érvényben maradnak · Esc megszakítja a húzást'})

HU.update({'Solid tools': 'Testeszközök', 'Construct': 'Szerkesztőgeometria', 'Construction': 'Szerkesztőgeometria', 'Construction Plane': 'Szerkesztősík', 'Construction Axis': 'Szerkesztőtengely', 'Revolve': 'Forgatás', 'Sweep': 'Söprés', 'Loft': 'Átmeneti test', 'Shell': 'Héjképzés', 'Draft': 'Ferde fal', 'Hole': 'Furat', 'Offset plane': 'Eltolt sík', 'Angled plane': 'Döntött sík', 'Midplane': 'Felezősík', 'Three-point plane': 'Hárompontos sík', 'Axis': 'Tengely', 'X axis': 'X tengely', 'Y axis': 'Y tengely', 'Z axis': 'Z tengely', 'XY plane': 'XY sík', 'XZ plane': 'XZ sík', 'YZ plane': 'YZ sík', 'Plane type': 'Sík típusa', 'Reference plane': 'Referenciasík', 'Second plane': 'Második sík', 'Offset': 'Eltolás', 'offset': 'eltolt', 'angled': 'döntött', 'midplane': 'felezősík', 'three points': 'három pont', 'Two points': 'Két pont', 'Select…': 'Válassz…', 'Saved reference': 'Mentett referencia', 'Profile': 'Profil', 'Path': 'Útvonal', 'Next section': 'Következő szelvény', 'Sections in order': 'Szelvények sorrendben', 'Add section': 'Szelvény hozzáadása', 'Remove section': 'Szelvény eltávolítása', 'Move section up': 'Szelvény mozgatása felfelé', 'Move section down': 'Szelvény mozgatása lefelé', 'Ruled loft': 'Egyenes alkotójú átmenet', 'Frenet orientation': 'Frenet-orientáció', 'Neutral plane': 'Semleges sík', 'Draft angle': 'Ferdítési szög', 'Open faces': 'Eltávolítandó felületek', 'Draft faces': 'Ferdítendő felületek', 'Thickness (negative = inward)': 'Falvastagság (negatív = befelé)', 'Pick faces in workspace': 'Felületek kijelölése a munkaterületen', 'Create sketch on this plane': 'Vázlat létrehozása ezen a síkon', 'Supporting plane': 'Hordozósík', 'Hole type': 'Furat típusa', 'simple': 'egyszerű', 'counterbore': 'hengeres süllyesztés', 'countersink': 'kúpos süllyesztés', 'Head diameter': 'Süllyesztés átmérője', 'Head depth': 'Süllyesztés mélysége', 'Included angle': 'Kúpszög', 'Through all': 'Átmenő', 'through all': 'átmenő', 'to object': 'objektumig', 'distance': 'megadott távolság', 'Extent': 'Kiterjedés', 'Target': 'Cél', 'Taper angle': 'Ferdítési szög', 'inward': 'befelé', 'outward': 'kifelé', 'Pick target face': 'Célfelület kijelölése', 'Pick supporting plane face': 'Hordozófelület kijelölése', 'Pick reference plane face': 'Referenciafelület kijelölése', 'Pick second plane face': 'Második felület kijelölése', 'Pick neutral plane face': 'Semleges felület kijelölése', 'Pick start point': 'Kezdőpont kijelölése', 'Pick end point': 'Végpont kijelölése', 'Pick P1': 'P1 kijelölése', 'Pick P2': 'P2 kijelölése', 'Pick P3': 'P3 kijelölése', 'Preparing feature references…': 'Művelethivatkozások előkészítése…', 'Finding sketch profiles…': 'Vázlatprofilok keresése…', 'Choose a model corner or sketch point.': 'Jelölj ki egy modellcsúcsot vagy vázlatpontot.', 'Double-click a plane to start a sketch. Edit construction parameters from the timeline.': 'Vázlat indításához kattints duplán egy síkra. A szerkesztőgeometria paraméterei az idővonalon szerkeszthetők.', 'The profile must meet the start of the connected path and be perpendicular to it. Tight bends may self-intersect.': 'A profilnak a folytonos útvonal kezdőpontjához kell csatlakoznia, és merőlegesnek kell lennie rá. Szűk kanyarokban önmetszés keletkezhet.', 'Shell: select faces to remove, or leave empty for a closed hollow body.': 'Héjképzés: jelöld ki az eltávolítandó felületeket, vagy hagyd üresen a zárt üreges testhez.', 'Draft rotates selected faces about the neutral plane. Positive angles remove material in the plane-normal direction.': 'A ferdítés a kijelölt felületeket a semleges sík körül dönti meg. A pozitív szög a síknormális irányában távolít el anyagot.', 'X and Y are coordinates on the supporting plane. A face support starts at its center; inward points into the body.': 'Az X és Y a hordozósík koordinátái. A felület origója annak középpontja; a befelé irány a test belsejébe mutat.', 'Click a face in the workspace; drag to orbit. Click again to toggle multiple faces.': 'Kattints egy felületre a munkaterületen; húzással forgathatsz. Újabb kattintással válthatod a felület kijelölését.', 'Click a face to select it · drag to orbit · use the right panel to finish': 'Kattintás: felület kijelölése · húzás: forgatás · befejezés a jobb oldali panelen', 'Click a model corner or sketch point · the picked coordinates are stored in the feature': 'Kattints modellcsúcsra vagy vázlatpontra · a kijelölt koordináták a műveletben tárolódnak', 'Select a closed sketch profile.': 'Jelölj ki egy zárt vázlatprofilt.', 'Select a connected sweep path.': 'Jelölj ki egy folytonos söprési útvonalat.', 'Construction guides cannot be used as solid profiles.': 'A segédgeometria nem használható testprofilként.', 'The inward shell exceeds the available material. Reduce its thickness.': 'A befelé készülő héj meghaladja a rendelkezésre álló anyagot. Csökkentsd a falvastagságot.', 'The hole misses the body. Check the supporting plane, position and direction.': 'A furat nem éri el a testet. Ellenőrizd a hordozósíkot, a pozíciót és az irányt.', 'Midplanes require parallel reference planes.': 'A felezősíkhoz párhuzamos referenciasíkok szükségesek.', 'Select a rotation or construction axis.': 'Jelölj ki egy forgatási vagy szerkesztőtengelyt.'})

HU.update({'Body tools': 'Testműveletek', 'Move / Copy': 'Mozgatás / Másolás', 'Body mirror': 'Test tükrözése', 'Rectangular pattern': 'Téglalap alakú kiosztás', 'Circular pattern': 'Körkiosztás', 'Split body': 'Test felosztása', 'Combine bodies': 'Testek kombinálása', 'Repair': 'Javítás', 'Target bodies': 'Céltestek', 'Target body': 'Céltest', 'Tool bodies': 'Szerszámtestek', 'Create copies': 'Másolatok létrehozása', 'Keep originals': 'Eredetik megtartása', 'Keep tool bodies': 'Szerszámtestek megtartása', 'Translation X': 'X eltolás', 'Translation Y': 'Y eltolás', 'Translation Z': 'Z eltolás', 'Rotation angle': 'Forgatási szög', 'Pattern angle': 'Kiosztási szög', 'Total positions': 'Pozíciók száma összesen', 'Keep side': 'Megtartandó oldal', 'both': 'mindkettő', 'positive': 'pozitív', 'negative': 'negatív', 'join': 'egyesítés', 'Inspect / Repair references': 'Hivatkozások ellenőrzése / javítása', 'Replace selected reference': 'Kijelölt hivatkozás cseréje', 'Rebuild and apply repairs': 'Újraépítés és javítások alkalmazása', 'Discard pending edit': 'Függő módosítás elvetése', 'Show selected reference': 'Kijelölt hivatkozás megjelenítése', 'recovered': 'helyreállítva', 'matched': 'azonosítva', 'valid': 'érvényes', 'blocked': 'blokkolva', 'needs repair': 'javítást igényel', 'suppressed': 'kikapcsolva', 'Pending upstream edit; the committed model is unchanged.': 'Függő előzmény-módosítás; a mentett modell változatlan.', 'Inspecting the committed feature history.': 'A mentett művelettörténet ellenőrzése.', 'features recovered': 'művelet hivatkozásai helyreállítva', 'Rebuild is blocked at feature': 'Az újraépítést blokkoló művelet', 'All features rebuild successfully.': 'Minden művelet sikeresen újraépül.', 'Select a stored face, edge or body reference to inspect or replace it.': 'Válassz mentett felület-, él- vagy testhivatkozást az ellenőrzéshez vagy cseréhez.', 'Repair the earlier failing feature first.': 'Először javítsd a korábbi hibás műveletet.', 'Current reference': 'Aktuális hivatkozás', 'Sketch support': 'Vázlat hordozósíkja', 'Faces': 'Felületek', 'Edges': 'Élek', 'body': 'test', 'face': 'felület', 'edge': 'él', 'Inspecting downstream references…': 'Későbbi műveletek hivatkozásainak ellenőrzése…', 'Preparing repair candidates…': 'Javítási lehetőségek előkészítése…', 'Rebuilding repaired history…': 'Javított művelettörténet újraépítése…', 'Pick target bodies in workspace': 'Céltestek kijelölése a munkaterületen', 'Pick target body in workspace': 'Céltest kijelölése a munkaterületen', 'Pick tool bodies in workspace': 'Szerszámtestek kijelölése a munkaterületen', 'Only explicitly selected bodies are changed. Copies and patterns remain separate bodies; use Combine to join them.': 'Csak a kijelölt testek módosulnak. A másolatok és kiosztások külön testek maradnak; egyesítésükhöz használd a Testek kombinálása eszközt.', 'Full circles include the original and omit the duplicate 360° position. Partial patterns include both ends.': 'A teljes körkiosztás tartalmazza az eredetit, és kihagyja az ismétlődő 360°-os pozíciót. A részleges kiosztás mindkét végpontot tartalmazza.'})

HU.update({'Import STEP': 'STEP importálása', 'Import STEP…': 'STEP importálása…', 'Import DXF': 'DXF importálása', 'Import DXF…': 'DXF importálása…', 'Export DXF': 'DXF exportálása', 'Export DXF…': 'DXF exportálása…', 'Recover autosave': 'Automatikus mentés helyreállítása', 'Recover autosave…': 'Automatikus mentés helyreállítása…', 'Recover': 'Helyreállítás', 'Choose an interrupted session. Your original project file is unchanged.': 'Válassz egy megszakadt munkamenetet. Az eredeti projektfájl változatlan marad.', 'No recoverable autosaves were found.': 'Nem található helyreállítható automatikus mentés.', 'Recovered session. Save the project to keep your changes.': 'A munkamenet helyreállítva. A módosítások megtartásához mentsd a projektet.', 'Autosave failed:': 'Az automatikus mentés nem sikerült:', 'Recovering autosave…': 'Automatikus mentés helyreállítása…', 'Looking for autosave recovery…': 'Helyreállítható automatikus mentések keresése…', 'Importing STEP…': 'STEP importálása…', 'Importing DXF…': 'DXF importálása…', 'Exporting DXF…': 'DXF exportálása…', 'DXF drawing (*.dxf)': 'DXF rajz (*.dxf)', 'Sketch plane': 'Vázlat síkja', 'DXF imported.': 'DXF importálva.', 'Unitless DXF treated as millimeters.': 'A mértékegység nélküli DXF méretei milliméterben értendők.', 'Skipped unsupported DXF entities:': 'Kihagyott, nem támogatott DXF-elemek:', 'Create a sketch before exporting DXF.': 'DXF exportálásához először hozz létre vázlatot.', 'Imported STEP': 'Importált STEP', 'Import scale': 'Importálási méretarány', 'Replace STEP source…': 'STEP forrás cseréje…', 'Replace STEP source': 'STEP forrás cseréje', 'Spline type': 'Spline típusa', 'Spline degree': 'Spline fokszáma', 'Closed curve': 'Zárt görbe', 'Conic weight': 'Kúpszelet súlya', 'catmull': 'Interpoláló spline (korábbi)', 'bspline': 'Vezérlőponti B-spline', 'Invalid embedded STEP geometry.': 'Érvénytelen beágyazott STEP-geometria.', 'STEP must contain valid closed solid bodies.': 'A STEP-fájlnak érvényes, zárt testeket kell tartalmaznia.', 'DXF sketch geometry must lie in the XY plane (Z = 0).': 'A DXF vázlatgeometriának az XY síkban kell lennie (Z = 0).', 'DXF contains no supported sketch geometry.': 'A DXF nem tartalmaz támogatott vázlatgeometriát.', 'Curve intersection failed; the sketch was kept.': 'A görbék metszésének számítása nem sikerült; a vázlat megmaradt.', 'Spline weights must be positive and match the control points.': 'A spline súlyainak pozitívnak kell lenniük, és minden vezérlőponthoz egy súly szükséges.'})

HU.update({'Construct':'Segédgeometria','Import scale':'Méretarány','Apply feature':'Alkalmazás','TOOLS':'ESZKÖZÖK','MODE':'MÓD'})
HU.update({'CREATE':'LÉTREHOZÁS','MODIFY':'MÓDOSÍTÁS','CONSTRAINTS':'KÉNYSZEREK','INSPECT':'VIZSGÁLAT','Solid modify':'Test módosítása','More modify':'További módosítás','Body patterns':'Testminták','Delete feature':'Művelet törlése','Delete feature history':'Művelet törlése'})

PHRASES={
'features · Volume':'művelet · Térfogat','all dimensions in mm':'minden méret mm-ben','entities ·':'elem ·','entities':'elem','closed profiles':'zárt profil',
'on face':'felületen','origin plane':'alapsíkon','sources selected':'forrás kijelölve','source selected':'forrás kijelölve','faces':'felület','profiles':'profil',
'edges selected':'él kijelölve','edge selected':'él kijelölve','Maximum fillet radius for selected edges:':'A kijelölt élek maximális lekerekítési sugara:','Maximum chamfer distance for selected edges:':'A kijelölt élek maximális letörési távolsága:',
'History preview · model after feature':'Előzmény előnézet · modell a(z)','right-click the timeline feature to revert here':'jobb kattintás a műveletre a visszaállításhoz','Showing history after feature':'Előzmény megjelenítése a(z)',
'Reverted to feature':'Visszaállítva a(z)','Undo restores the removed feature history.':'A Visszavonás visszaállítja az eltávolított műveleteket.',
'Body ':'Test ',' appearance':' megjelenése','Corner ':'Sarok ','Control ':'Vezérlő ','Line ':'Vonal ','Center at ':'Középpont: ',
'Sources selected:':'Kijelölt források:','Guide line:':'Vezetővonal:','Center point:':'Középpont:','Current step:':'Aktuális lépés:',
'Click geometry to toggle selection.':'Kattints a geometriára a kijelölés váltásához.','Selecting source geometry.':'Forrásgeometria kijelölése.','Selecting the guide line.':'Vezetővonal kijelölése.','Selecting the center point.':'Középpont kijelölése.',
'Created ':'Létrehozva: ',' editable entities. Undo reverses the entire operation.':' szerkeszthető elem. A Visszavonás az egész műveletet visszaállítja.',
'Editing ':'Szerkesztés: ','Select at least one source entity.':'Jelölj ki legalább egy forráselemet.','Select geometry other than the guide line.':'A vezetővonalon kívüli geometriát jelölj ki.',
'No valid ':'Nincs érvényes ',' size found':' méret','Maximum ':'Maximum ',' size ≈ ':' méret ≈ ','Checking ':'Ellenőrzés: ',' limit · ':' határ · ','Building feature ':'Művelet építése: ',' of ':' / ',
'Preparing viewport face ':'Nézetfelület előkészítése: ','Preparing viewport edge ':'Nézetél előkészítése: ','Preparing GPU vertex data':'GPU csúcspontadatok előkészítése','Viewport ready':'Nézet kész','Model rebuild complete':'Modell újraépítve',
'Click a face/profile to add or remove it':'Kattints felületre/profilra a hozzáadáshoz vagy eltávolításhoz','all selected sources extrude together':'minden kijelölt forrás együtt kerül kihúzásra',
'mm grid':'mm rács','snap:':'illesztés:','locked':'rögzítve','current':'aktuális',
'Line':'Vonal','Arc':'Ív','Rectangle':'Téglalap','Circle':'Kör','Trim':'Levágás','Guide':'Segédgeometria','Ellipse':'Ellipszis','Slot':'Horony','Conic':'Kúpszelet','Point':'Pont','Polygon':'Sokszög','Mirror':'Tükrözés','grid':'rács','face':'felület','profile':'profil','edge':'él','selected':'kijelölve',
'SKETCH ·':'VÁZLAT ·','EXTRUDE ·':'KIHÚZÁS ·','Feature ':'Művelet ',' SOURCE':' FORRÁS',' SOURCES':' FORRÁS',' SELECTED':' KIJELÖLVE','LINE':'VONAL','ARC':'ÍV','RECTANGLE':'TÉGLALAP','CIRCLE':'KÖR','TRIM':'LEVÁGÁS','GUIDE':'SEGÉDGEOMETRIA','ELLIPSE':'ELLIPSZIS','SLOT':'HORONY','SPLINE':'SPLINE','CONIC':'KÚPSZELET','POINT':'PONT','POLYGON':'SOKSZÖG','MIRROR':'TÜKRÖZÉS','CIRCULAR':'KÖRKIOSZTÁS','RECTANGULAR':'TÉGLALAP ALAKÚ KIOSZTÁS',
'Later features (':'Későbbi műveletek (',') are temporarily hidden; nothing has been deleted.':') ideiglenesen rejtve van; semmi sem lett törölve.','Showing the model immediately after feature':'A modell megjelenítése közvetlenül a(z)','Revert the project to feature':'Projekt visszaállítása a(z)','This removes':'Ez eltávolít','later feature':'későbbi művelet','from the current history. You can Undo to restore them.':'az aktuális előzményből. Visszavonással helyreállíthatók.','selected · click another face/profile to add it, or click a selected one to remove it.':'kijelölve · kattints másik felületre/profilra a hozzáadáshoz, vagy a kijelöltre az eltávolításhoz.','selected</b> · click model edges to toggle selection':'kijelölve</b> · kattints a modell éleire a kijelölés váltásához','Click the center, then a vertex to place a':'Kattints a középpontra, majd egy csúcsra egy','-sided polygon.':'oldalú sokszög elhelyezéséhez.','Corner ':'Sarok ',' · guide':' · segéd',
}

def load_language():
    value=app_settings().value('appearance/language','en')
    return value if value in ('en','hu') else 'en'

def save_language(value):
    if value not in ('en','hu'):raise ValueError('Unknown language')
    settings=app_settings();settings.setValue('appearance/language',value);settings.sync()

def set_language(value):
    global _LANGUAGE
    _LANGUAGE=value if value in ('en','hu') else 'en'

def language():return _LANGUAGE

def _phrase_pattern(source):
    prefix=r'(?<![A-Za-z])' if source[0].isalpha() else ''
    suffix=r'(?![A-Za-z])' if source[-1].isalpha() else ''
    return prefix+re.escape(source)+suffix

_PHRASE_RE=re.compile('|'.join(_phrase_pattern(src) for src in sorted(PHRASES,key=len,reverse=True)))

_ERROR_TEMPLATES=[(re.compile(pattern,re.DOTALL),template) for pattern,template in (
    (r'(.+) depends on suppressed feature (.+)\. Suppress its dependents too, or repair their inputs\.','A(z) {} a(z) {} elnyomott műveletre épül. Nyomd el a függő műveleteket is, vagy javítsd a bemeneteiket.'),
    (r'(.+) requires a missing feature\. Repair its dependency\.','A(z) {} hiányzó műveletet igényel. Javítsd a függőségét.'),
    (r'(.+) must be a finite positive number\.','A(z) {} véges, pozitív szám kell legyen.'),
    (r'(.+) must be finite\.','A(z) {} értéke véges kell legyen.'),
    (r'(.+) requires (\d+) selected references\.','A(z) {} esetén {} hivatkozást kell kijelölni.'),
    (r'Cannot reorder (.+) before required feature (.+)\.','A(z) {} nem helyezhető a szükséges {} elé.'),
    (r'Cannot save (.+)','Nem menthető: {}'),
)]

def tr(text):
    if text is None or _LANGUAGE!='hu':return text
    text=str(text)
    if text in HU:return HU[text]
    # Paths and user-entered feature names must survive language switching.
    if text.startswith('Exported '):return 'Exportálva: '+text[len('Exported '):]
    error=re.fullmatch(r'Feature (\d+) \((.*)\): (.*)',text,re.DOTALL)
    if error:return f'{error[1]}. művelet ({error[2]}): '+tr(error[3])
    progress=re.fullmatch(r'Building feature (\d+) of (\d+)(?::| ·) (.*)',text,re.DOTALL)
    if progress:return f'{progress[1]}/{progress[2]}. művelet újraépítése: {progress[3]}'
    # Counted progress messages built with f-strings.
    counted=re.fullmatch(r'Preparing viewport (face|edge) (\d+) of (\d+)',text)
    if counted:return f"Nézet előkészítése: {'felület' if counted[1]=='face' else 'él'} {counted[2]}/{counted[3]}"
    # Error messages that carry a feature or parameter name.
    for pattern,template in _ERROR_TEMPLATES:
        found=pattern.fullmatch(text)
        if found:return template.format(*[tr(group) for group in found.groups()])
    # Translate text nodes only; do not rewrite HTML attributes or translated output.
    return ''.join(part if part.startswith('<') else _PHRASE_RE.sub(lambda match:PHRASES[match.group()],part)
                   for part in re.split(r'(<[^>]*>)',text))

def _english_source(text):
    if text in HU:return text
    reverse={value:key for key,value in HU.items()}
    return reverse.get(text,text)

def localize_tree(root):
    """Translate ordinary Qt text widgets while retaining an English source string."""
    from PySide6.QtWidgets import QLabel,QPushButton,QToolButton,QCheckBox,QGroupBox
    widgets=[]
    # PySide does not accept a tuple in all versions, so use separate passes.
    if hasattr(root,'findChildren'):
        widgets=[root]
        for cls in (QLabel,QPushButton,QToolButton,QCheckBox,QGroupBox):widgets.extend(root.findChildren(cls))
    seen=set()
    for widget in widgets:
        if id(widget) in seen:continue
        seen.add(id(widget))
        if isinstance(widget,QGroupBox):
            current=widget.title();source=widget.property('_i18n_title') or _english_source(current)
            if current and widget.property('_i18n_title') is None:widget.setProperty('_i18n_title',source)
            if source:widget.setTitle(tr(source))
        elif hasattr(widget,'text') and hasattr(widget,'setText'):
            current=widget.text();source=widget.property('_i18n_text') or _english_source(current)
            if current and widget.property('_i18n_text') is None:widget.setProperty('_i18n_text',source)
            if source:widget.setText(tr(source))
        if hasattr(widget,'toolTip') and hasattr(widget,'setToolTip') and widget.toolTip():
            current=widget.toolTip();source=widget.property('_i18n_tooltip') or _english_source(current)
            if widget.property('_i18n_tooltip') is None:widget.setProperty('_i18n_tooltip',source)
            widget.setToolTip(tr(source))

HU.update({
    'Move sketch':'Vázlat mozgatása',
    'Move':'Mozgatás',
    'Create a sketch first.':'Először hozz létre egy vázlatot.',
    'Type a distance in mm; Tab switches axes. Apply keeps the change.':'Adj meg egy távolságot mm-ben; a Tab tengelyt vált. Az Alkalmazás véglegesíti a módosítást.',
    'Drag the X/Y/Z handles or type exact distances. Tab switches axes. Moving a sketch updates its downstream features. Dashed lines are drag guides; Preview builds the exact result. Apply keeps the change.':'Húzd az X/Y/Z fogantyúkat, vagy adj meg pontos távolságokat. A Tab tengelyt vált. A vázlat mozgatása frissíti a rá épülő műveleteket. A szaggatott vonalak segédvonalak; az Előnézet megmutatja a pontos eredményt. Az Alkalmazás véglegesíti a módosítást.',
    'Preparing workspace handles…':'Munkatéri fogantyúk előkészítése…',
    'Select a sketch to move.':'Válassz ki egy mozgatandó vázlatot.',
    'The sketch has no geometry.':'A vázlat nem tartalmaz geometriát.',
    'The sketch to move is missing, suppressed or later in history.':'A mozgatandó vázlat hiányzik, le van tiltva, vagy később szerepel a műveleti előzményekben.',
})

HU.update({'Fix':'Rögzítés','Unfix':'Rögzítés feloldása','Midpoint':'Felezőpont','Concentric':'Koncentrikus','Collinear':'Egy egyenesre illesztés','Point on object':'Pont objektumra illesztése','Fully constrained':'Teljesen kényszerezett','Degrees of freedom':'Szabadságfokok','Sketch parameters':'Vázlatparaméterek','Reference dimension':'Referencia-méret','Reference':'Referencia','Expression':'Kifejezés','Add parameter':'Paraméter hozzáadása','Delete selected parameter':'Kijelölt paraméter törlése','Optional dimension name':'Opcionális méretnév','Optional expression, e.g. pitch * 2':'Opcionális kifejezés, pl. pitch * 2'})

HU.update({'Project / Include':'Vetítés / Befoglalás','Project / Include geometry':'Geometria vetítése / befoglalása','Project':'Vetítés','Include':'Befoglalás','Model edges':'Testélek','Project selected geometry':'Kijelölt geometria vetítése','Break selected projection link':'Kijelölt vetítés kapcsolatának megszüntetése','Projecting associative geometry…':'Asszociatív geometria vetítése…'})

HU.update({
'Project / Include':'Vetítés / Bevonás','Projected geometry':'Vetített geometria','Linked geometry':'Kapcsolt geometria',
'Break selected projection link':'Kijelölt vetítési kapcsolat megszüntetése','Break projection link':'Vetítési kapcsolat megszüntetése',
'Break the projection link before editing this geometry.':'A geometria szerkesztése előtt szüntesd meg a vetítési kapcsolatot.',
'Feature dependencies':'Műveletfüggőségek','Required inputs':'Szükséges bemenetek','Downstream dependents':'Függő műveletek',
'Inspect dependencies':'Függőségek vizsgálata','Move earlier':'Előrébb helyezés','Move later':'Hátrébb helyezés','Suppress':'Letiltás','Unsuppress':'Engedélyezés','Suppress with dependents':'Letiltás a függő műveletekkel együtt',
'Press Pull':'Nyomás / Húzás','Scale':'Méretezés','Offset Face':'Felület eltolása','Split Face':'Felület felosztása','Replace Face':'Felület cseréje',
'Selection type':'Kijelölés típusa','Scale factor':'Méretarány','Scale center':'Méretezés középpontja','Splitting profile':'Felosztó profil','Replacement plane':'Cserefelület síkja',
'Feature Rectangular':'Műveletek téglalap-kiosztása','Feature Circular':'Műveletek körkiosztása','Feature Mirror':'Műveletek tükrözése','Path Pattern':'Kiosztás görbe mentén','Objects':'Objektumok','features':'műveletek','faces':'felületek','bodies':'testek','Features':'Műveletek','Feature faces':'Műveletfelületek','Orient along path':'Igazítás a görbéhez',
'Surface':'Felület','Surfaces':'Felületek','Surface Extrude':'Felület kihúzása','Surface Revolve':'Felület forgatása','Surface Sweep':'Felület söprése','Surface Loft':'Felület átmenete','Surface Patch':'Felületfolt','Surface Trim':'Felület levágása','Surface Extend':'Felület meghosszabbítása','Surface Stitch':'Felületek összevarrása','Surface Thicken':'Felület vastagítása',
'Boundary':'Határgörbe','Surface bodies':'Felülettestek','Trim plane':'Levágási sík','Extension':'Meghosszabbítás','Tolerance':'Tűrés','Make solid':'Szilárd test létrehozása','Consume source surfaces':'Forrásfelületek felhasználása','Directions':'Irányok',
'Primitive':'Primitív test','Pipe':'Cső','Coil':'Tekercs','Rib':'Borda','Web':'Merevítő gerinc','Thread':'Menet','box':'téglatest','cylinder':'henger','sphere':'gömb','cone':'kúp','torus':'tórusz',
'Origin':'Origó','Radius':'Sugár','Minor Radius':'Kis sugár','Top Radius':'Felső sugár','Wire diameter':'Huzalátmérő','Wall thickness':'Falvastagság','Hollow':'Üreges','Left hand':'Balmenetes','Thread type':'Menet típusa','external':'külső','internal':'belső','Thread depth':'Menetmélység','Thread width':'Menetszélesség','Pitch':'Menetemelkedés',
'Assembly':'Összeállítás','Component':'Komponens','Components':'Komponensek','Joint':'Kapcsolat','New component':'Új komponens','Return to parent assembly':'Visszatérés a szülő összeállításhoz','Edit component history':'Komponenselőzmények szerkesztése','Editing component':'Komponens szerkesztése','Grounded':'Rögzített','Moving component':'Mozgó komponens','Fixed component':'Rögzített komponens','Assembly origin':'Összeállítás origója','Joint type':'Kapcsolat típusa','Joint origin':'Kapcsolat origója','Joint axis':'Kapcsolat tengelye','Alignment offset':'Illesztési eltolás','Motion preview':'Mozgás előnézete','Axial position':'Tengelyirányú helyzet','rigid':'merev','revolute':'forgó','slider':'csúszó','cylindrical':'hengeres','Minimum':'Minimum','Maximum':'Maximum','Position':'Helyzet','Rotation':'Forgatás','Rotation axis':'Forgatási tengely',
'3D sketch':'3D vázlat','Sketch3D':'3D vázlat','Sketch on surface':'Vázlat felületen','Surface sketch':'Felületvázlat','Surface Sketch':'Felületvázlat','Supporting face':'Hordozó felület','Pick supporting face':'Hordozó felület kijelölése','Drawing plane':'Rajzsík','Plane offset':'Sík eltolása','Curve':'Görbe','Add point from coordinates':'Pont hozzáadása koordinátákból','Finish spline':'Spline befejezése','End curve / clear pending points':'Görbe befejezése / függő pontok törlése','Geometry':'Geometria','Points':'Pontok','Back':'Vissza',
'Click within the supporting face.':'Kattints a hordozó felületen belül.','Select a supporting face first.':'Először válassz hordozó felületet.','Rotate the view so the drawing plane is visible.':'Forgassa úgy a nézetet, hogy a rajzsík látható legyen.','Double-click to edit component history.':'Dupla kattintással szerkeszthetők a komponens előzményei.'
})

HU.update({'Closed spline':'Zárt spline'})

HU.update({'CONSTRUCT':'SEGÉDGEOMETRIA'})

# 0.12.1 review fixes
HU.update({'Find maximum size':'Legnagyobb méret keresése',
 'Tests trial sizes with the CAD kernel; this can take a few seconds.':'Próbaméreteket ellenőriz a CAD-maggal; ez néhány másodpercig tarthat.',
 'Maximum for selected edges: click Find maximum size to check.':'A kijelölt élek legnagyobb mérete: kattints a Legnagyobb méret keresése gombra.',
 'Project opened with an error':'A projekt hibával nyílt meg',
 'The model is shown up to the last working feature':'A modell az utolsó működő műveletig látható',
 'Edit, suppress or repair the failing feature; later features are kept but not built until it works.':'Szerkeszd, kapcsold ki vagy javítsd a hibás műveletet; a későbbi műveletek megmaradnak, de csak utána épülnek fel.',
 'Not built: an earlier feature fails.':'Nincs felépítve: egy korábbi művelet hibás.',
 'Discard selected':'Kijelölt elvetése','Discard all':'Összes elvetése','Later':'Később',
 'Could not delete autosave:':'Az automatikus mentés nem törölhető:'})

# 0.12.3 fillet robustness and toolbar
HU.update({'Tangent chain':'Érintőlánc',
 'Clicking an edge also selects the edges joined to it smoothly, as in Fusion. Rounded outlines need the whole chain.':'Egy élre kattintva a hozzá simán csatlakozó élek is kijelölődnek, mint a Fusionben. Lekerekített körvonalaknál a teljes lánc kell.',
 'Size too large':'Túl nagy méret','is too large for these edges.':'túl nagy ezekhez az élekhez.','The largest':'A legnagyobb','that works is about':'ami működik, kb.',

 'No size works for this edge selection.':'Ehhez az élkijelöléshez egyetlen méret sem működik.',
 'Remove edges that meet very small or curved faces, select fewer edges, or turn Tangent chain on or off and try again.':'Vedd ki a nagyon kicsi vagy görbült felületekhez csatlakozó éleket, jelölj ki kevesebb élt, vagy kapcsold be/ki az Érintőláncot, és próbáld újra.'})
HU.update({'Fit size automatically':'Méret automatikus illesztése',
 'If the size is too large for some edges, those edges get the largest size that fits instead of the feature failing.':'Ha a méret egyes élekhez túl nagy, azok az élek a legnagyobb még működő méretet kapják, és a művelet nem hiúsul meg.',
 'Edges using a smaller size (largest that fits):':'Kisebb méretet kapott élek (a legnagyobb, ami elfér):','Edges skipped (no size fits):':'Kihagyott élek (egy méret sem fér el):',
 'Radius':'Sugár','Distance':'Távolság','Thickness':'Vastagság','Offset':'Eltolás','Depth':'Mélység'})
HU.update({'Measure closed.':'Mérés bezárva.','Tool canceled · Select':'Eszköz megszakítva · Kijelölés','Canceled.':'Megszakítva.'})
HU.update({
 'Drag a rectangle to place the text box.':'Húzz egy téglalapot a szövegdoboz elhelyezéséhez.',
 'Drag a rectangle for the text box. Its text, font, size and alignment are set here afterwards.':'Húzz egy téglalapot a szövegdobozhoz. A szöveget, a betűtípust, a méretet és az igazítást utána itt állíthatod be.',
 'Type the text, choose the font and alignment; the outline in the workspace shows how it will look. Place text (Ctrl+Enter) adds it to the sketch as closed outlines.':'Írd be a szöveget, válaszd ki a betűtípust és az igazítást; a munkaterületen látható körvonal mutatja a végeredményt. A Szöveg elhelyezése (Ctrl+Enter) zárt körvonalként adja a vázlathoz.',
 'Text box position and size':'Szövegdoboz helye és mérete','Left':'Bal szél','Bottom':'Alsó él','Width':'Szélesség','Height':'Magasság',
 'Fit box to text':'Doboz igazítása a szöveghez','Place text':'Szöveg elhelyezése','Cancel text':'Szöveg elvetése',
 'Line spacing':'Sorköz','Wrap text to the box width':'Sortörés a doboz szélességénél',
 'Font size in points (1 pt = 0.353 mm).':'Betűméret pontban (1 pt = 0,353 mm).',
 'B':'F','I':'D','U':'A','Bold':'Félkövér','Italic':'Dőlt','Underline':'Aláhúzott',
 'Align left':'Balra igazítás','Align center':'Középre igazítás','Align right':'Jobbra igazítás','Justify':'Sorkizárt',
 'Align top':'Felülre igazítás','Align middle':'Középre igazítás függőlegesen','Align bottom':'Alulra igazítás',
 'Text':'Szöveg','Box':'Doboz','line':'sor','lines':'sor',
 'The text is wider than the box.':'A szöveg szélesebb a doboznál.','The text is taller than the box.':'A szöveg magasabb a doboznál.',
 'Text placed.':'A szöveg elhelyezve.','Text canceled.':'A szöveg elvetve.',
 'Place or cancel the current text before drawing a new text box.':'Helyezd el vagy vesd el a jelenlegi szöveget, mielőtt új szövegdobozt rajzolsz.',
 'Drag the text box larger than a point.':'A szövegdoboz legyen nagyobb egy pontnál.',
 'Text is too long (limit: 4000 characters).':'A szöveg túl hosszú (legfeljebb 4000 karakter).',
 'Text size must be positive.':'A szövegméretnek pozitívnak kell lennie.','Line spacing must be positive.':'A sorköznek pozitívnak kell lennie.',
 'Text: click the first corner of the text box':'Szöveg: kattints a szövegdoboz első sarkára','Text: click the opposite corner':'Szöveg: kattints a szemközti sarokra',
 'Text: set the text and format in the right panel · Ctrl+Enter places it · Esc cancels':'Szöveg: a szöveg és a formázás a jobb oldali panelen állítható · Ctrl+Enter: elhelyezés · Esc: elvetés',
})
HU.update({'Horizontal':'Vízszintes','Vertical':'Függőleges'})
HU.update({'Select all profiles': 'Összes profil kijelölése', 'Adds every closed profile of the visible sketches.': 'Hozzáadja a látható vázlatok minden zárt profilját.', 'Drag selects a box': 'A húzás kijelölő téglalapot rajzol', 'Off: Shift+drag draws the selection box and plain drag orbits. On: plain drag draws the box.': 'Ki: a Shift+húzás rajzolja a kijelölő téglalapot, a sima húzás forgat. Be: a sima húzás is téglalapot rajzol.', 'Click profiles or faces to add or remove them. Shift+drag draws a selection box: left to right selects what is fully inside, right to left what it touches; Ctrl+Shift removes.': 'Kattints profilokra vagy felületekre a hozzáadáshoz vagy eltávolításhoz. A Shift+húzás kijelölő téglalapot rajzol: balról jobbra a teljesen benne lévőket, jobbról balra az érintettet jelöli ki; Ctrl+Shift eltávolít.', 'Nothing new inside the box.': 'Nincs új elem a téglalapban.', 'Nothing inside the box.': 'Nincs elem a téglalapban.', 'There are no visible sketch profiles to select.': 'Nincs kijelölhető, látható vázlatprofil.', 'This tool takes a single face: click the face you want.': 'Ez az eszköz egy felületet kér: kattints a kívántra.', 'Toggle construction guide': 'Segédvonal ki-be kapcsolása', 'sketch entities selected': 'vázlatelem kijelölve', 'sketch entities deleted': 'vázlatelem törölve', 'edges selected': 'él kijelölve', 'Delete removes them; Shift+drag adds more, Ctrl+Shift+drag removes.': 'A Delete törli őket; Shift+húzás többet ad hozzá, Ctrl+Shift+húzás eltávolít.', 'Live preview': 'Élő előnézet', 'Update the preview automatically after each change.': 'Az előnézet minden módosítás után magától frissül.', 'Live preview turned off: this model rebuilds slowly. Use Preview.': 'Az élő előnézet kikapcsolt: ez a modell lassan épül újra. Használd az Előnézet gombot.', 'Click the faces to open (Shift+drag draws a selection box); drag to orbit.': 'Kattints a megnyitandó felületekre (Shift+húzás: kijelölő téglalap); húzással forgathatsz.', 'Click the faces to draft (Shift+drag draws a selection box); drag to orbit.': 'Kattints a döntendő felületekre (Shift+húzás: kijelölő téglalap); húzással forgathatsz.', 'Click the faces to use (Shift+drag draws a selection box); drag to orbit.': 'Kattints a használni kívánt felületekre (Shift+húzás: kijelölő téglalap); húzással forgathatsz.', 'Click the face the hole starts on; drag to orbit.': 'Kattints arra a felületre, ahol a furat kezdődik; húzással forgathatsz.', 'Click a closed sketch profile to use it (loft: click each section in order).': 'Kattints egy zárt vázlatprofilra (átmenet: kattints sorban az egyes szelvényekre).', 'Pick a closed sketch profile.': 'Válassz egy zárt vázlatprofilt.', 'Release to select · left to right: inside the box · right to left: touching the box · Ctrl+Shift: remove': 'Engedd el a kijelöléshez · balról jobbra: a téglalapon belüliek · jobbról balra: az érintettek · Ctrl+Shift: eltávolítás', 'Click a face to select it · Shift+drag a box to select many · drag to orbit': 'Kattints egy felületre a kijelöléshez · Shift+húzás: több kijelölése téglalappal · húzás: forgatás'})
HU.update({
'What this does: it copies edges of your solid, or lines of another sketch, into THIS sketch so you can draw next to them and make profiles that line up exactly. Project flattens the geometry onto this sketch plane (use it for edges on other faces or at an angle); Include keeps it as it is (it should already lie in this plane). The copy stays linked and follows the source until you press Break link. How: click edges on the model, or pick them in the list, then press the button.':
'Mit csinál: a test éleit vagy egy másik vázlat vonalait átmásolja EBBE a vázlatba, hogy mellettük rajzolhass, és pontosan illeszkedő profilokat készíthess. A Vetítés a geometriát erre a vázlatsíkra lapítja (más lapon lévő vagy ferde élekhez); a Befoglalás változatlanul tartja (már ebben a síkban kell lennie). A másolat összekapcsolt marad, és követi a forrást, amíg a Kapcsolat megszüntetése gombot meg nem nyomod. Hogyan: kattints élekre a modellen, vagy válaszd ki őket a listában, majd nyomd meg a gombot.',
'Project flattens onto the sketch plane. Include keeps the geometry as it is.':'A Vetítés a vázlatsíkra lapít. A Befoglalás változatlanul tartja a geometriát.',
'Center arc: click the center point':'Középpontos ív: kattints a középpontra',
'Center arc: click the start point on the arc':'Középpontos ív: kattints az ív kezdőpontjára',
'Center arc: move around the center, click where the arc should end':'Középpontos ív: mozgasd a középpont körül, és kattints, ahol az ívnek véget kell érnie',
'3-point circle: click the first point on the circle':'3 pontos kör: kattints a kör első pontjára',
'3-point circle: click the second point':'3 pontos kör: kattints a második pontra',
'3-point circle: click the third point':'3 pontos kör: kattints a harmadik pontra'})
HU.update({
'Click to sketch on this construction plane':'Kattints, hogy erre a segédsíkra rajzolj',
'Click to use this curve as the path':'Kattints, hogy ezt a görbét használd pályaként',
'Click one of the sketch curves to use it as the path.':'Kattints egy vázlatgörbére, hogy pályaként használd.',
'Pick a closed sketch profile or a planar face.':'Válassz egy zárt vázlatprofilt vagy egy sík felületet.',
'Click each section in order: a closed sketch profile or a planar face.':'Kattints sorban az egyes szelvényekre: zárt vázlatprofilra vagy sík felületre.',
'Click the closed sketch profile (or planar face) to use.':'Kattints a használni kívánt zárt vázlatprofilra (vagy sík felületre).',
'Click a sketch curve to use it as the path (connected curves are taken together).':'Kattints egy vázlatgörbére, hogy pályaként használd (az összefüggő görbék együtt kerülnek kiválasztásra).',
'Path selected · click another curve to change it.':'Pálya kiválasztva · kattints másik görbére a váltáshoz.',
'Click the profile in the workspace':'Profil kiválasztása a munkaterületen',
'Click the path in the workspace':'Pálya kiválasztása a munkaterületen',
'Click the sections in the workspace':'Szelvények kiválasztása a munkaterületen',
'Click the body to pattern in the workspace.':'Kattints a sokszorozandó testre a munkaterületen.',
'Click the body in the workspace':'Test kiválasztása a munkaterületen',
'Click a cylindrical face (a shaft or a hole wall) to put the thread or coil on it.':'Kattints egy hengeres felületre (tengely vagy furat fala), hogy a menet vagy a csavarvonal arra kerüljön.',
'That face is not cylindrical. Click the wall of a shaft or a round hole.':'Ez a felület nem hengeres. Kattints egy tengely vagy kerek furat falára.',
'Cylinder taken: radius, length and axis are set. Adjust pitch and size, then Preview.':'Henger átvéve: a sugár, a hossz és a tengely be van állítva. Állítsd be a menetemelkedést és a méretet, majd Előnézet.',
'Click a cylindrical face in the workspace':'Hengeres felület kiválasztása a munkaterületen',
'Click the round wall of a shaft or a hole in the workspace: its axis, radius and length are taken over. The thread is cut as a helical groove (external on a shaft, internal in a hole). Pitch = distance between turns.':'Kattints egy tengely vagy furat kerek falára a munkaterületen: a tengelye, sugara és hossza átvételre kerül. A menet csavarvonalú horonyként kerül kivágásra (tengelyen külső, furatban belső). Menetemelkedés = a menetek közti távolság.',
'Click the round wall of a shaft or a hole in the workspace: its axis, radius and length are taken over. The coil is a wire wound around that axis (a spring). Pitch = distance between turns.':'Kattints egy tengely vagy furat kerek falára a munkaterületen: a tengelye, sugara és hossza átvételre kerül. A csavarvonal egy e tengely köré csavart drót (rugó). Menetemelkedés = a menetek közti távolság.',
'Rib: a thin supporting wall that stands on the sketch line you picked (it grows from the sketch plane along its normal), used to stiffen a part between two walls. Web: the same wall centred on the sketch plane, half above and half below, for cross-bracing. Draw the line or curve of the wall in a sketch, click it, then set the wall Thickness and Height.':'Borda: vékony merevítő fal, amely a kiválasztott vázlatvonalon áll (a vázlatsík normálisa mentén nő), két fal közötti alkatrész merevítésére. Gerinc: ugyanaz a fal a vázlatsíkra középre igazítva, fele fent, fele lent, keresztmerevítéshez. Rajzold meg a fal vonalát vagy görbéjét egy vázlatban, kattints rá, majd add meg a fal Vastagságát és Magasságát.',
'1. Choose what to repeat: features, faces or whole bodies.  2. Click the body in the workspace (or tick it in Target bodies).  3. Set the count and spacing: the result previews by itself.':'1. Válaszd ki, mit sokszorozz: műveleteket, felületeket vagy egész testeket.  2. Kattints a testre a munkaterületen (vagy jelöld be a Cél testek között).  3. Állítsd be a darabszámot és a távolságot: az eredmény magától előnézetként megjelenik.',
'Click the first point of the axis (a corner or a sketch point), then the second.':'Kattints a tengely első pontjára (sarok vagy vázlatpont), majd a másodikra.',
'Click three points (corners or sketch points) one after another.':'Kattints három pontra (sarok vagy vázlatpont) egymás után.',
'Click the first face, then choose the second plane on the right.':'Kattints az első felületre, majd válaszd ki a második síkot jobb oldalon.',
'Click a face to build the plane from (or choose a plane on the right).':'Kattints egy felületre, amelyből a sík készül (vagy válassz síkot jobb oldalon).',
'Point set. Click the next point.':'Pont beállítva. Kattints a következő pontra.'})
HU.update({'BROWSER':'BÖNGÉSZŐ','Collapse / expand':'Összecsukás / kibontás'})
HU.update({
'Welcome to SlothCAD':'Üdvözöl a SlothCAD',
'What do you want to do?':'Mit szeretnél csinálni?',
'New project':'Új projekt','Open project…':'Projekt megnyitása…','Import a file…':'Fájl importálása…',
'Open the example part':'A példa alkatrész megnyitása','Recent projects':'Legutóbbi projektek',
'Close other projects':'A többi projekt bezárása','Paste copied features here':'Másolt műveletek beillesztése ide',
'Copy feature (with what it needs)':'Művelet másolása (a függőségeivel)','Paste feature into this project':'Művelet beillesztése ebbe a projektbe',
'Select a feature in the history first, then copy it.':'Előbb jelölj ki egy műveletet az előzményekben, aztán másold.',
'Copied:':'Átmásolva:','open another project and paste with Ctrl+V.':'nyiss meg másik projektet, és illeszd be Ctrl+V-vel.',
'Nothing to paste: copy a feature first (Ctrl+C).':'Nincs mit beilleszteni: előbb másolj egy műveletet (Ctrl+C).',
'Pasted features:':'Beillesztett műveletek:','Pasting features…':'Műveletek beillesztése…'})
HU.update({'Click to look from this side':'Kattints, hogy erről az oldalról nézd'})
HU.update({'Start with an empty project':'Indulj üres projekttel','Open an existing .fcad file':'Meglévő .fcad fájl megnyitása','Bring in a STEP solid or a DXF drawing':'STEP test vagy DXF rajz behozatala','Example part':'Példa alkatrész','Open the example part and explore':'A példa alkatrész megnyitása és felfedezése','Projects you open or save will show up here.':'Az itt megnyitott vagy mentett projektek itt jelennek meg.'})
HU.update({'About SlothCAD…':'A SlothCAD-ról…','About SlothCAD':'A SlothCAD-ról','SlothCAD is free and open-source software, released under the GNU General Public License v3.0. You may use, study, change and share it; versions you share must stay under the same license.':'A SlothCAD szabad, nyílt forráskódú szoftver, a GNU General Public License v3.0 licenc alatt kiadva. Használhatod, tanulmányozhatod, módosíthatod és megoszthatod; a megosztott változatoknak ugyanezen licenc alatt kell maradniuk.','It is built on Qt for Python (LGPL), CadQuery (Apache-2.0) and OpenCASCADE (LGPL).':'A Qt for Python (LGPL), a CadQuery (Apache-2.0) és az OpenCASCADE (LGPL) projektekre épül.'})
HU.update({'Show the grid through bodies':'A rács látszik a testeken át'})
HU.update({'Frame rate':'Képkockasebesség','Automatic (match the display)':'Automatikus (a kijelzőhöz igazítva)','display limit':'meghaladja a kijelzőt'})
HU.update({'Display refresh rate:':'Kijelző frissítési frekvenciája:','frame limit:':'képkockakorlát:'})
HU.update({'Grid display':'Rács megjelenítése',
'Axes display':'Tengelyek megjelenítése',
'new':'új',
'Positions':'Pozíciók',
'Plane':'Sík',
'Replace Face supports parallel planar replacements. Other surface boundaries need surface modeling first.':'A felületcsere párhuzamos, sík helyettesítést támogat. Más felületi határokhoz előbb felületmodellezés szükséges.',
'Extrusion':'Kihúzás',
'Body Mirror':'Test tükrözése',
'Body Rectangular':'Testek téglalap-kiosztása',
'Body Circular':'Testek körkiosztása',
'Click a body to select it; drag to orbit.':'Kattints egy testre a kijelöléshez; húzással forgathatsz.',
'Click a body to select it, arrows then appear to move it live; drag to orbit.':'Kattints egy testre a kijelöléshez, majd nyilak jelennek meg az élő mozgatáshoz; húzással forgathatsz.',
'Select a body from the feature input, before this operation.':'Ehhez a művelethez előbb válassz ki egy testet a bemenetek közül.',
'Click the corners where sketch curves meet to select them (click again to deselect). Drag the arrow or type a size, then apply. The outline shows the real result; sizes above the largest possible are not offered.':'Kattints azokra a sarkokra, ahol a vázlatgörbék találkoznak (újabb kattintással megszűnik a kijelölés). Húzd a nyilat vagy írj be egy méretet, majd alkalmazd. A körvonal a valós eredményt mutatja; a lehetséges legnagyobb méretnél nagyobb értékek nem választhatók.',
'Clear selection':'Kijelölés törlése',
'Apply chamfer':'Letörés alkalmazása',
'Apply fillet':'Lekerekítés alkalmazása',
'Mode':'Mód',
'Source':'Forrás',
'Construction geometry':'Segédvonal',
'Edit dimension':'Méret szerkesztése',
'None':'Nincs',
'target bodies':'céltest',
'Click a corner first.':'Előbb kattints egy sarokra.',
'Linked geometry is read-only. Break its projection link before editing.':'A kapcsolt geometria csak olvasható. Szerkesztés előtt szüntesd meg a vetítési kapcsolatot.',
'The last valid model is unchanged. Inspect downstream references to repair this pending edit.':'Az utolsó érvényes modell változatlan. Vizsgáld meg a későbbi hivatkozásokat, hogy kijavítsd ezt a függő módosítást.',
'The joint drives one component relative to the assembled position. Joint origin and axis are local to the fixed component, or world coordinates when using Assembly origin. Motion is limited; interference is not a collision constraint.':'A kapcsolat az egyik komponenst az összeállított helyzethez képest mozgatja. A kapcsolat origója és tengelye a rögzített komponenshez képest helyi, vagy világkoordináta, ha az összeállítás origóját használod. A mozgás korlátozott; az átfedés nem ütközési kényszer.',
'U and V are native surface parameters: angles on cylinders, lengths on planes. Curves are built on the surface, not on its tangent plane.':'Az U és a V a felület saját paraméterei: hengereken szögek, síkokon hosszak. A görbék magán a felületen épülnek, nem az érintősíkján.',
'cannot be built at this size':'ezen a méreten nem építhető fel',
'intersects a body':'metszi a testet',
'Construction Plane':'Segédsík',
'Construction Axis':'Segédtengely',
'Construction':'Segédgeometria',
'Select a rotation or construction axis.':'Jelölj ki egy forgási vagy segédtengelyt.',
'Vector':'Vektor',
'Normal':'Normál'})
HU.update({'A C compiler is needed. On Fedora, install gcc and rerun the installer.':'C fordítóra van szükség. Fedorán telepítsd a gcc-t, majd futtasd újra a telepítőt.',
'A component needs its own feature history.':'Egy komponensnek saját műveleti előzményre van szüksége.',
'A constraint references geometry that was removed.':'Egy kényszer olyan geometriára hivatkozik, amelyet eltávolítottak.',
'A curve on a surface is not a straight rotation axis. Choose a straight 3D line or construction axis.':'A felületen lévő görbe nem egyenes forgástengely. Válassz egyenes 3D vonalat vagy segédtengelyt.',
'A joint component is missing, suppressed or later in history.':'A kapcsolat egyik komponense hiányzik, el van nyomva, vagy később van az előzményekben.',
'A joint needs two distinct components, or the assembly origin.':'A kapcsolathoz két különböző komponens vagy az összeállítás origója kell.',
'A patterned feature is missing, suppressed or later in history.':'A kiosztott művelet hiányzik, el van nyomva, vagy később van az előzményekben.',
'A projected sketch entity was removed. Repair its source.':'Egy vetített vázlatelemet eltávolítottak. Javítsd ki a forrását.',
'A spatial path curve is missing or is a point.':'A térbeli pályagörbe hiányzik, vagy csak egy pont.',
'A spatial sketch needs a geometry list.':'A térbeli vázlathoz geometrialista kell.',
'A surface body is missing or suppressed. Repair its selection.':'Egy felülettest hiányzik vagy el van nyomva. Javítsd ki a kijelölését.',
'Adjacent curve points must be distinct.':'A szomszédos görbepontoknak különbözniük kell.',
'An angled-plane rotation axis must lie in its reference plane.':'A döntött sík forgástengelyének a referenciasíkjában kell lennie.',
'Chamfer distance is too large for the adjacent sketch edges.':'A letörés távolsága túl nagy a szomszédos vázlatélekhez.',
'Choose Join, Cut or Intersect.':'Válaszd az Egyesítés, Kivágás vagy Metszet lehetőséget.',
'Choose New body, Join, Cut or Intersect.':'Válaszd az Új test, Egyesítés, Kivágás vagy Metszet lehetőséget.',
'Choose Project or Include geometry.':'Válaszd a Vetítés vagy a Befoglalás lehetőséget.',
'Choose U, V or all extension directions.':'Válaszd az U, a V vagy az összes meghosszabbítási irányt.',
'Choose a corner with a visible change in direction.':'Válassz olyan sarkot, ahol látható irányváltás van.',
'Choose a sketch endpoint or center.':'Válassz egy vázlat végpontot vagy középpontot.',
'Choose a supported joint type.':'Válassz támogatott kapcsolattípust.',
'Choose a valid history feature.':'Válassz érvényes előzményműveletet.',
'Choose at least one source sketch entity.':'Válassz legalább egy forrás vázlatelemet.',
'Choose both, positive or negative split sides.':'Válaszd mindkét, a pozitív vagy a negatív felosztási oldalt.',
'Choose two distinct points or a nonzero axis direction.':'Válassz két különböző pontot vagy nem nulla tengelyirányt.',
'Choose valid feature positions.':'Válassz érvényes művelet-pozíciókat.',
'Coil diameter must be smaller than the pitch and twice the helix radius.':'A tekercs vastagságának kisebbnek kell lennie a menetemelkedésnél és a csavarvonal sugarának kétszeresénél.',
'Combine requires exactly one target body.':'Az egyesítéshez pontosan egy céltest kell.',
'Component ancestry contains a missing identity or a cycle.':'A komponens felmenői között hiányzó azonosító vagy kör van.',
'Component motion produced invalid geometry.':'A komponens mozgása érvénytelen geometriát hozott létre.',
'Component nesting exceeds 32 levels.':'A komponensek egymásba ágyazása meghaladja a 32 szintet.',
'Cone top radius must be nonnegative and differ from the base radius.':'A kúp felső sugara nem lehet negatív, és el kell térnie az alapsugártól.',
'Construction curves cannot be joined to regular sketch curves.':'A segédgörbék nem köthetők össze a szokásos vázlatgörbékkel.',
'Could not measure this geometry pair.':'Ez a geometriapár nem mérhető.',
'Could not project onto curve.':'Nem lehet a görbére vetíteni.',
'Counterbore depth must not exceed the hole depth.':'A süllyesztés mélysége nem haladhatja meg a furat mélységét.',
'Countersink angle must be between 0 and 180 degrees.':'A kúpos süllyesztés szögének 0 és 180 fok között kell lennie.',
'Create a target body first, or choose New body.':'Előbb hozz létre egy céltestet, vagy válaszd az Új test lehetőséget.',
'Create geometry before exporting.':'Exportálás előtt hozz létre geometriát.',
'DXF curves must use the positive XY plane normal.':'A DXF-görbéknek a pozitív XY sík normálvektorát kell használniuk.',
'DXF ellipses must use the positive XY plane normal.':'A DXF-ellipsziseknek a pozitív XY sík normálvektorát kell használniuk.',
'Dimension expression is too complex.':'A méretkifejezés túl összetett.',
'Dimension expression is too deeply nested.':'A méretkifejezés túl mélyen egymásba ágyazott.',
'Draft angle must be nonzero and between -89 and 89 degrees.':'A ferdítési szög nem lehet nulla, és -89 és 89 fok között kell lennie.',
'Duplicate component identity.':'Ismétlődő komponens-azonosító.',
'Duplicate construction ID.':'Ismétlődő segédgeometria-azonosító.',
'Duplicate sketch identity.':'Ismétlődő vázlatazonosító.',
'Duplicate sketch or construction ID.':'Ismétlődő vázlat- vagy segédgeometria-azonosító.',
'Enter a finite primitive origin.':'Adj meg véges alaptest-origót.',
'Enter a finite scale center.':'Adj meg véges méretezési középpontot.',
'Enter a nonzero angle up to 360 degrees.':'Adj meg nullától különböző, legfeljebb 360 fokos szöget.',
'Enter a nonzero finite extrusion vector.':'Adj meg nullától különböző, véges kihúzási vektort.',
'Enter a nonzero revolve angle up to 360 degrees.':'Adj meg nullától különböző, legfeljebb 360 fokos forgatási szöget.',
'Enter a nonzero translation or rotation.':'Adj meg nullától különböző eltolást vagy forgatást.',
'Enter both a parameter name and an expression.':'Add meg a paraméter nevét és a kifejezést is.',
'Enter finite X, Y and Z coordinates.':'Adj meg véges X, Y és Z koordinátákat.',
'Expression exponent must be between -32 and 32.':'A kifejezés kitevőjének -32 és 32 között kell lennie.',
'Expression result must be finite and within ±10¹².':'A kifejezés eredményének végesnek kell lennie, ±10¹² határon belül.',
'Expressions allow numbers, parameter names, arithmetic and supported math functions only.':'A kifejezések csak számokat, paraméterneveket, számtani műveleteket és támogatott matematikai függvényeket tartalmazhatnak.',
'Extend a surface without inner trim loops.':'Csak belső vágóhurkok nélküli felületet lehet meghosszabbítani.',
'Extend requires an untrimmed rectangular UV boundary. Extending arbitrary trim edges is not supported yet.':'A meghosszabbításhoz levágatlan, téglalap alakú UV-határ kell. A tetszőleges vágóélek meghosszabbítása még nem támogatott.',
'Face patterns need one target body.':'A felületkiosztáshoz egy céltest kell.',
'Fillet radius is too large for the adjacent sketch edges.':'A lekerekítés sugara túl nagy a szomszédos vázlatélekhez.',
'Imported geometry has no valid solids.':'Az importált geometriában nincs érvényes tömör test.',
'Include geometry must lie in this sketch plane. Use Project, or include it in a 3D sketch.':'A befoglalt geometriának ebben a vázlatsíkban kell lennie. Használd a Vetítést, vagy foglald be 3D vázlatba.',
'Included point is outside the sketch plane.':'A befoglalt pont a vázlatsíkon kívül van.',
'Invalid arithmetic in dimension expression.':'Érvénytelen számtani művelet a méretkifejezésben.',
'Invalid constraint reference.':'Érvénytelen kényszerhivatkozás.',
'Invalid dimension expression.':'Érvénytelen méretkifejezés.',
'Invalid or duplicate constraint ID.':'Érvénytelen vagy ismétlődő kényszerazonosító.',
'Invalid or duplicate projection ID.':'Érvénytelen vagy ismétlődő vetületazonosító.',
'Invalid recovered component context.':'Érvénytelen helyreállított komponenskörnyezet.',
'Invalid recovered component history.':'Érvénytelen helyreállított komponenselőzmény.',
'Invalid recovered feature index.':'Érvénytelen helyreállított műveletindex.',
'Invalid recovered project path.':'Érvénytelen helyreállított projektútvonal.',
'Invalid rectangle corner reference.':'Érvénytelen téglalapsarok-hivatkozás.',
'Invalid saved body reference. Repair its reference.':'Érvénytelen mentett testhivatkozás. Javítsd ki a hivatkozást.',
'Invalid sketch constraint.':'Érvénytelen vázlatkényszer.',
'Invalid sketch point reference.':'Érvénytelen vázlatpont-hivatkozás.',
'Invalid sketch projection list.':'Érvénytelen vázlatvetület-lista.',
'Invalid spline control points or degree.':'Érvénytelen spline-vezérlőpontok vagy fokszám.',
'Invalid spline knot vector.':'Érvénytelen spline csomóvektor.',
'Invalid trimmed curve interval.':'Érvénytelen vágott görbeintervallum.',
'Join requires touching or overlapping bodies. Disconnected bodies stay separate.':'Az egyesítéshez érintkező vagy átfedő testek kellenek. A különálló testek különállóak maradnak.',
'Joint position is outside its motion limits.':'A kapcsolat helyzete a mozgási határain kívül van.',
'Offset distance cannot be zero.':'Az eltolás távolsága nem lehet nulla.',
'Parameter dependency chain is too long.':'A paraméterfüggőségi lánc túl hosszú.',
'Parameter names must be identifiers distinct from units and math functions.':'A paraméterneveknek azonosítóknak kell lenniük, és el kell térniük a mértékegységektől és a matematikai függvényektől.',
'Parameter values must be finite numbers or expressions.':'A paraméterértékeknek véges számoknak vagy kifejezéseknek kell lenniük.',
'Patch needs a closed boundary.':'A foltozáshoz zárt határ kell.',
'Patterned material is disconnected from the target. Use a body pattern for separate copies.':'A kiosztott anyag nem kapcsolódik a céltesthez. Különálló másolatokhoz használj testkiosztást.',
'Patterns need features that change solid material.':'A kiosztáshoz olyan műveletek kellenek, amelyek a tömör anyagot változtatják.',
'Pipe thickness must be less than half its diameter.':'A cső falvastagságának kisebbnek kell lennie az átmérő felénél.',
'Projected geometry has duplicate entity IDs.':'A vetített geometriában ismétlődő elemazonosítók vannak.',
'Reference dimensions are measured and cannot drive expressions.':'A referenciaméretek mért értékek, és nem vezérelhetnek kifejezéseket.',
'Revolve angle must be nonzero and at most 360 degrees.':'A forgatási szög nem lehet nulla, és legfeljebb 360 fok lehet.',
'Rib paths must lie in the sketch plane.':'A borda pályájának a vázlatsíkban kell lennie.',
'STEP contains solids the kernel reports as invalid, even after repair.':'A STEP olyan testeket tartalmaz, amelyeket a kernel javítás után is érvénytelennek jelez.',
'STEP must contain closed solid bodies.':'A STEP-nek zárt tömör testeket kell tartalmaznia.',
'Select a path sketch.':'Válassz egy pályavázlatot.',
'Select a straight sketch line for the axis.':'Válassz egyenes vázlatvonalat a tengelyhez.',
'Select a target body explicitly.':'Jelölj ki kifejezetten egy céltestet.',
'Select a target body.':'Jelölj ki egy céltestet.',
'Select a valid body.':'Jelölj ki egy érvényes testet.',
'Select at least one path curve.':'Jelölj ki legalább egy pályagörbét.',
'Select at least one target body explicitly.':'Jelölj ki kifejezetten legalább egy céltestet.',
'Select distinct bodies.':'Jelölj ki különböző testeket.',
'Select distinct surface bodies explicitly.':'Jelölj ki kifejezetten különböző felülettesteket.',
'Select distinct target bodies explicitly.':'Jelölj ki kifejezetten különböző céltesteket.',
'Select distinct target bodies.':'Jelölj ki különböző céltesteket.',
'Select distinct tool bodies, separate from the target.':'Jelölj ki különböző szerszámtesteket, amelyek külön vannak a céltesttől.',
'Select linked geometry first.':'Előbb jelölj ki kapcsolt geometriát.',
'Select one or more distinct earlier features.':'Jelölj ki egy vagy több különböző korábbi műveletet.',
'Select one or two measurement objects.':'Jelölj ki egy vagy két mérendő objektumot.',
'Select spatial path curves.':'Jelölj ki térbeli pályagörbéket.',
'Shell thickness cannot be zero.':'A héj vastagsága nem lehet nulla.',
'Sketch constraints must be a list.':'A vázlatkényszereknek listának kell lenniük.',
'Sketch parameters must be finite.':'A vázlatparamétereknek végesnek kell lenniük.',
'Spatial curves need finite coordinates and enough control points.':'A térbeli görbékhez véges koordináták és elegendő vezérlőpont kell.',
'Stitch to solid needs one watertight closed shell. Repair gaps or leave Make solid off.':'A testté varráshoz egyetlen vízzáró, zárt héj kell. Javítsd a réseket, vagy hagyd kikapcsolva a „Tömör test” beállítást.',
'Stitch tolerance must not exceed 1 mm.':'Az összevarrási tűrés nem haladhatja meg az 1 mm-t.',
'Surface Loft failed. Check section order and connectivity.':'A felületi átmenet nem sikerült. Ellenőrizd a szelvények sorrendjét és kapcsolódását.',
'Surface Loft needs at least two ordered sections.':'A felületi átmenethez legalább két, rendezett szelvény kell.',
'Sweep paths require connected lines, arcs or splines.':'A söprési pályához összefüggő vonalak, ívek vagy spline-ok kellenek.',
'Taper angle must be between -89 and 89 degrees.':'A dőlésszögnek -89 és 89 fok között kell lennie.',
'The UV spline cannot be interpolated.':'Az UV-spline nem interpolálható.',
'The axis sketch is missing.':'A tengelyvázlat hiányzik.',
'The component bodies changed topology outside their own history. Edit the component history before adding a joint.':'A komponens testeinek topológiája a saját előzményükön kívül változott. Kapcsolat hozzáadása előtt szerkeszd a komponens előzményét.',
'The construction axis is missing, suppressed or later in history.':'A segédtengely hiányzik, el van nyomva, vagy később van az előzményekben.',
'The construction plane is missing, suppressed or later in history.':'A segédsík hiányzik, el van nyomva, vagy később van az előzményekben.',
'The countersink is deeper than the hole.':'A süllyesztés mélyebb, mint a furat.',
'The curve length is too small.':'A görbe hossza túl kicsi.',
'The feature must connect to the target body.':'A műveletnek kapcsolódnia kell a céltesthez.',
'The head diameter must exceed the hole diameter.':'A fej átmérőjének nagyobbnak kell lennie a furat átmérőjénél.',
'The projection source sketch is missing or later in history. Repair its source.':'A vetítés forrásvázlata hiányzik, vagy később van az előzményekben. Javítsd ki a forrását.',
'The referenced body identity is missing. Repair its reference; another body will not be substituted.':'A hivatkozott test azonosítója hiányzik. Javítsd ki a hivatkozást; másik test nem kerül a helyére.',
'The referenced body no longer exists.':'A hivatkozott test már nem létezik.',
'The source surface is missing or suppressed. Repair its reference.':'A forrásfelület hiányzik vagy el van nyomva. Javítsd ki a hivatkozását.',
'The source surface is missing.':'A forrásfelület hiányzik.',
'The spatial path sketch is missing.':'A térbeli pályavázlat hiányzik.',
'The sweep path must be one connected wire.':'A söprési pályának egyetlen összefüggő vonalláncnak kell lennie.',
'The target body changed too much. Repair its body reference.':'A céltest túl sokat változott. Javítsd ki a testhivatkozást.',
'The target plane is parallel to the extrusion direction.':'A célsík párhuzamos a kihúzás irányával.',
'The tool bodies do not intersect the target.':'A szerszámtestek nem metszik a céltestet.',
'These features do not add or remove material. Select a solid feature.':'Ezek a műveletek nem adnak hozzá és nem vesznek el anyagot. Jelölj ki tömör anyagot változtató műveletet.',
'Thicken failed. Reduce thickness or repair surface intersections.':'A vastagítás nem sikerült. Csökkentsd a vastagságot, vagy javítsd a felületek metszéseit.',
'Thickness cannot be zero.':'A vastagság nem lehet nulla.',
'This component already has a driving joint. Edit that joint or suppress it first.':'Ennek a komponensnek már van vezérlő kapcsolata. Előbb szerkeszd vagy nyomd el azt.',
'This constraint requires a circle.':'Ehhez a kényszerhez kör kell.',
'This constraint requires straight lines or polygon edges.':'Ehhez a kényszerhez egyenes vonalak vagy sokszögélek kellenek.',
'This curve is invalid. Check coincident points or arc collinearity.':'Ez a görbe érvénytelen. Ellenőrizd az egybeeső pontokat vagy az ív pontjainak egy egyenesre esését.',
'This extent needs an existing body.':'Ehhez a kiterjedéshez meglévő test kell.',
'This feature misses the target body. Check its path, position and size.':'Ez a művelet nem érinti a céltestet. Ellenőrizd a pályáját, helyzetét és méretét.',
'This item has no measurable boundary.':'Ennek az elemnek nincs mérhető határa.',
'This joint would create a cyclic assembly chain.':'Ez a kapcsolat körkörös összeállítási láncot hozna létre.',
'This legacy feature needs a persistent identity before it can be safely reordered.':'Ennek a régi műveletnek tartós azonosító kell, mielőtt biztonságosan áthelyezhető lenne.',
'This operation would remove all bodies.':'Ez a művelet az összes testet eltávolítaná.',
'This pattern exceeds 500 bodies. Reduce the count.':'Ez a kiosztás meghaladja az 500 testet. Csökkentsd a darabszámot.',
'This pattern exceeds 500 body copies.':'Ez a kiosztás meghaladja az 500 testmásolatot.',
'This surface cannot extend beyond its natural domain.':'Ez a felület nem hosszabbítható meg a természetes tartományán túl.',
'To-object extrusion uses one side. Choose distance or through-all for a symmetric extrusion.':'Az objektumig tartó kihúzás egy oldalra szól. Szimmetrikus kihúzáshoz válassz távolságot vagy átmenőt.',
'Torus minor radius must be smaller than its major radius.':'A tórusz kis sugarának kisebbnek kell lennie a nagy sugaránál.',
'Unground the moving component before adding a joint.':'Kapcsolat hozzáadása előtt oldd fel a mozgó komponens rögzítését.',
'Unknown body tool.':'Ismeretlen testeszköz.',
'Unknown construction plane mode.':'Ismeretlen segédsík-mód.',
'Unknown corner tool.':'Ismeretlen sarokeszköz.',
'Unknown extrusion extent.':'Ismeretlen kihúzási kiterjedés.',
'Unknown hole type.':'Ismeretlen furattípus.',
'Unknown horizontal alignment.':'Ismeretlen vízszintes igazítás.',
'Unknown plane reference.':'Ismeretlen síkhivatkozás.',
'Unknown polygon sizing mode.':'Ismeretlen sokszög-méretezési mód.',
'Unknown primitive shape.':'Ismeretlen alaptest-forma.',
'Unknown reference type.':'Ismeretlen hivatkozástípus.',
'Unknown sketch constraint.':'Ismeretlen vázlatkényszer.',
'Unknown solid tool.':'Ismeretlen testeszköz.',
'Unknown surface tool.':'Ismeretlen felületeszköz.',
'Unknown vertical alignment.':'Ismeretlen függőleges igazítás.',
'Unsupported projection source.':'Nem támogatott vetítési forrás.',
'Unsupported sketch drag target.':'Nem támogatott vázlathúzási cél.',
'Unsupported sketch reference.':'Nem támogatott vázlathivatkozás.',
'Use at least two positions and a nonzero angle up to 360 degrees.':'Használj legalább két pozíciót és nullától különböző, legfeljebb 360 fokos szöget.',
'Use at least two positions and nonzero spacing for active directions.':'Használj legalább két pozíciót és nullától különböző távolságot az aktív irányokban.',
'Use at least two positions with nonzero spacing.':'Használj legalább két pozíciót nullától különböző távolsággal.',
'Use at most 1000 points per curve.':'Görbénként legfeljebb 1000 pontot használj.',
'Use at most 500 named parameters.':'Legfeljebb 500 nevesített paramétert használj.',
'Use no more than 200 helical turns per feature.':'Műveletenként legfeljebb 200 csavarvonal-menetet használj.',
'Use no more than 500 pattern positions.':'Legfeljebb 500 kiosztási pozíciót használj.',
'degenerate loop':'elfajult hurok',
'empty loop':'üres hurok',
'The fast viewport module is not available and no C compiler was found; SlothCAD uses its slower built-in renderer instead.':'A gyors nézetmodul nem érhető el, és nem található C fordító; a SlothCAD a lassabb beépített megjelenítőt használja.'})
HU.update({'Maximum for selected edges: calculating…':'A kijelölt élek maximuma: számítás folyamatban…',
 'The maximum size could not be calculated; the size is fitted when applying.':'A maximális méretet nem sikerült kiszámítani; a méret az alkalmazáskor illeszkedik.'})


# Parameters, section view, saved views, analysis, drawings, mates and the new feature options.
HU.update({k:v for k,v in {
    # menus and actions
    'Tools':'Eszközök','Parameters…':'Paraméterek…','Mass properties…':'Tömegjellemzők…','Check interference':'Ütközésvizsgálat',
    'Bill of materials…':'Anyagjegyzék…','Section view':'Metszeti nézet','Zoom to selection':'Ráközelítés a kijelölésre',
    'Import IGES / mesh…':'IGES / hálómodell importálása…','Export drawing…':'Rajz exportálása…','Export 3MF…':'3MF exportálása…',
    'Export glTF (.glb)…':'glTF (.glb) exportálása…','Export options…':'Exportálási beállítások…','Insert part from file…':'Alkatrész beszúrása fájlból…',
    'Perspective view':'Perspektivikus nézet','Save current view…':'Aktuális nézet mentése…','Delete saved view…':'Mentett nézet törlése…',
    'Camera orientation · saved views':'Kameranézet · mentett nézetek','Perspective camera (sketches always use the orthographic view)':'Perspektivikus kamera (a vázlatok mindig merőleges vetítésűek)','Turn view 90°':'Nézet forgatása 90°-kal','Turn the sketch view 90° clockwise (the sketch itself does not change)':'A vázlatnézet elforgatása 90°-kal az óramutató irányába (maga a vázlat nem változik)',
    'Section view: cut the model with a movable plane':'Metszeti nézet: a modell elmetszése mozgatható síkkal',
    'Fit all visible objects · Z: zoom to the selection':'Az összes látható objektum ráillesztése · Z: ráközelítés a kijelölésre',
    # parameters
    'Document parameters':'Dokumentumparaméterek','Named values for the whole project. Use them in any number box of a feature or in a sketch dimension, for example: width / 2 + 1.':'Elnevezett értékek az egész projekthez. Használhatod őket bármely művelet számmezőjében vagy vázlatméretben, például: szelesseg / 2 + 1.',
    'Add parameter':'Paraméter hozzáadása','Delete selected parameter':'Kijelölt paraméter törlése','Expression':'Kifejezés','Value':'Érték',
    'Checking parameters…':'Paraméterek ellenőrzése…','Return to the parent assembly to edit the document parameters.':'A dokumentumparaméterek szerkesztéséhez térj vissza a szülő összeállításhoz.',
    'Enter both a parameter name and an expression.':'Add meg a paraméter nevét és kifejezését is.',
    'Document parameters must be a table of names and expressions.':'A dokumentumparamétereknek nevek és kifejezések táblázatának kell lenniük.',
    'Parameter values must be numbers or expressions.':'A paraméterértékek számok vagy kifejezések lehetnek.',
    'Invalid document parameters.':'Érvénytelen dokumentumparaméterek.','Invalid feature expressions.':'Érvénytelen műveletkifejezések.',
    'Wall thickness':'Falvastagság',
    # section / views / opacity
    'Section':'Metszet','XY plane':'XY sík','XZ plane':'XZ sík','YZ plane':'YZ sík','Keep the other side':'A másik oldal megtartása',
    'Close the section view':'Metszeti nézet bezárása','Section view · move the plane with the position box; the cut side is shown in orange.':'Metszeti nézet · a síkot a pozíciómezővel mozgathatod; a vágási felület narancssárga.',
    'Views are saved from the 3D view, not while sketching.':'A nézeteket a 3D nézetből lehet menteni, vázlatkészítés közben nem.',
    'Save current view':'Aktuális nézet mentése','Name of the view':'A nézet neve','View saved:':'Nézet elmentve:','Delete saved view':'Mentett nézet törlése','View':'Nézet',
    'Invalid saved views.':'Érvénytelen mentett nézetek.','Opacity':'Átlátszatlanság','Below 100 % the body is drawn see-through.':'100 % alatt a test átlátszóan jelenik meg.',
    # analysis
    'Mass properties':'Tömegjellemzők','Material':'Anyag','Density':'Sűrűség','Custom density':'Egyéni sűrűség','Only the bodies shown in the browser':'Csak a böngészőben látható testek',
    'Volume':'Térfogat','Surface area':'Felület','Mass':'Tömeg','Center of mass':'Tömegközéppont','Principal moments of inertia':'Főtehetetlenségi nyomatékok',
    'Inertia tensor about the center of mass':'Tehetetlenségi tenzor a tömegközéppontra','Bodies':'Testek','Copy to clipboard':'Másolás a vágólapra',
    'There is no solid to measure.':'Nincs mérhető test.','Density must be a positive number.':'A sűrűségnek pozitív számnak kell lennie.',
    'Interference needs at least two bodies.':'Az ütközésvizsgálathoz legalább két test kell.','No interference found: no two bodies share volume.':'Nincs ütközés: két test sem metszi egymást.',
    'Interference':'Ütközés','These bodies overlap:':'Ezek a testek átfedik egymást:','Body':'Test','Overlap (mm³)':'Átfedés (mm³)','Checking interference…':'Ütközések keresése…',
    'Bill of materials':'Anyagjegyzék','Part':'Alkatrész','Quantity':'Mennyiség','Volume (mm³)':'Térfogat (mm³)','Save as CSV…':'Mentés CSV-ként…',
    'Save bill of materials':'Anyagjegyzék mentése','CSV table (*.csv)':'CSV táblázat (*.csv)',
    # export options and formats
    'Export options':'Exportálási beállítások','Mesh quality (STL, 3MF, glTF)':'Hálóminőség (STL, 3MF, glTF)','Draft · small files':'Vázlatos · kis fájlok','Standard':'Szabványos',
    'Fine · smooth curves':'Finom · sima görbék','Custom':'Egyéni','Largest deviation':'Legnagyobb eltérés','Largest angle between facets':'Lapok közötti legnagyobb szög',
    '3MF model (*.3mf)':'3MF modell (*.3mf)','glTF binary (*.glb)':'glTF bináris (*.glb)','Export 3MF':'3MF exportálása','Export GLB':'GLB exportálása',
    'Choose a .step, .stp, .stl, .3mf or .glb filename.':'Válassz .step, .stp, .stl, .3mf vagy .glb fájlnevet.','Mesh tolerances must be positive numbers.':'A hálótűréseknek pozitív számoknak kell lenniük.',
    'There is nothing visible to export.':'Nincs exportálható látható elem.','There is no solid geometry to export as 3MF.':'Nincs 3MF-be exportálható tömör geometria.',
    'Import model':'Modell importálása','Importing model…':'Modell importálása…','3D models (*.step *.stp *.iges *.igs *.stl *.obj *.3mf)':'3D modellek (*.step *.stp *.iges *.igs *.stl *.obj *.3mf)',
    'Choose a STEP, IGES, STL, OBJ or 3MF file.':'Válassz STEP, IGES, STL, OBJ vagy 3MF fájlt.','The IGES file could not be read.':'Az IGES fájl nem olvasható.',
    'The STL file is truncated.':'Az STL fájl csonka.','The 3MF file has no model.':'A 3MF fájlban nincs modell.','The mesh has no triangles.':'A hálónak nincsenek háromszögei.',
    'The mesh is not watertight, so it cannot become a solid. Repair the holes in a mesh editor first.':'A háló nem zárt, ezért nem válhat testté. Előbb javítsd ki a lyukakat egy hálószerkesztőben.',
    'Unsupported mesh format.':'Nem támogatott hálóformátum.',
    # drawings
    'Export drawing':'Rajz exportálása','Exporting drawing…':'Rajz exportálása…','Views':'Nézetek','Hidden lines (dashed)':'Rejtett vonalak (szaggatott)','Overall dimensions (DXF)':'Főméretek (DXF)',
    'Scale':'Méretarány','DXF drawing (*.dxf);;SVG graphic (*.svg)':'DXF rajz (*.dxf);;SVG grafika (*.svg)','Choose at least one view for the drawing.':'Válassz legalább egy nézetet a rajzhoz.',
    'The drawing scale must be a positive number.':'A rajz méretarányának pozitív számnak kell lennie.','The model has no edges to draw in the ':'A modellnek nincsenek rajzolható élei ebben a nézetben: ',
    'Front':'Elölnézet','Back':'Hátulnézet','Top':'Felülnézet','Bottom':'Alulnézet','Right':'Jobb oldalnézet','Left':'Bal oldalnézet','Iso':'Izometrikus',
    # assemblies and mates
    'Mate':'Illesztés','1. Pick a face of the moving component, 2. pick the face it should touch.':'1. Jelölj ki egy lapot a mozgó komponensen, 2. jelöld ki azt a lapot, amelyhez érnie kell.',
    'Moving face':'Mozgó lap','Target face':'Cél lap','Pick moving face':'Mozgó lap kijelölése','Pick target face':'Cél lap kijelölése','not picked yet':'még nincs kijelölve','picked':'kijelölve',
    'Gap':'Rés','Flush (faces point the same way)':'Egy síkba (a lapok azonos irányba néznek)','Center the faces on each other':'A lapok egymásra középpontozása',
    'A mate is re-evaluated whenever the model is rebuilt, so the part follows if the faces move.':'Az illesztés a modell minden újraépítésekor újraszámolódik, így az alkatrész követi a lapok mozgását.',
    'Pick a face of the moving component and a face of the other body to mate.':'Jelölj ki egy lapot a mozgó komponensen és egyet a másik testen az illesztéshez.',
    'A mate needs bodies to align.':'Az illesztéshez testek kellenek.','Mates align planar faces. Choose flat faces.':'Az illesztés sík lapokat igazít. Válassz sík lapokat.',
    'The first face must belong to the moving component.':'Az első lapnak a mozgó komponenshez kell tartoznia.',
    'The second face must belong to a different component or body.':'A második lapnak másik komponenshez vagy testhez kell tartoznia.',
    'Insert part':'Alkatrész beszúrása','Opening part…':'Alkatrész megnyitása…','Source file':'Forrásfájl','Reload from source file':'Újratöltés a forrásfájlból',
    'Reloaded from the source file. Apply to keep the update.':'Újratöltve a forrásfájlból. Az alkalmazással tarthatod meg a frissítést.',
    # features
    'Thin wall':'Vékony fal','Wall position':'Fal helyzete','Inside the outline':'A körvonalon belül','Outside the outline':'A körvonalon kívül','Centered on the outline':'A körvonalra középre',
    'Extrude only a wall of the given thickness along the outline instead of the whole profile.':'Csak a megadott vastagságú falat húzza ki a körvonal mentén a teljes profil helyett.',
    'Second distance':'Második távolság','Side 1':'1. oldal','Side 2':'2. oldal','Section analysis':'Metszetelemzés','Section':'Metszet','Pick face':'Lap választása','Picked face':'Választott lap','Click a flat face of the model: the section runs parallel to it':'Kattints a modell egy sík lapjára: a metszet azzal párhuzamos lesz','Distance of the cut along the plane normal · or drag the arrow in the view':'A vágás távolsága a sík normálisa mentén · vagy húzd a nyilat a nézetben','Click a flat face: the section plane is placed parallel to it. Esc cancels.':'Kattints egy sík lapra: a metszősík vele párhuzamosan kerül elhelyezésre. Az Esc megszakítja.','That face is curved. Pick a flat face for the section plane.':'Ez a lap görbült. Válassz sík lapot a metszősíkhoz.','Section parallel to the picked face · drag the arrow to move it.':'A metszet párhuzamos a választott lappal · a nyíl húzásával mozgatható.','Section analysis · drag the arrow or type the position; the cut face is shown hatched in orange.':'Metszetelemzés · húzd a nyilat vagy írd be a helyzetet; a vágott felület narancssárgán, vonalkázva látszik.','Face picking for the section canceled.':'A metszet lapválasztása megszakítva.','Dimension deleted; the sketch geometry is kept.':'Méret törölve; a vázlatgeometria megmaradt.','Constraint deleted; the sketch geometry is kept.':'Kényszer törölve; a vázlatgeometria megmaradt.','selected · Delete removes it (the sketch stays) · double-click edits the value':'kijelölve · Delete törli (a vázlat megmarad) · dupla kattintással módosítható az érték','selected · Delete removes it (the sketch stays)':'kijelölve · Delete törli (a vázlat megmarad)','Every body this feature could change is hidden. Show the body, or choose New body.':'Minden test, amelyet ez a művelet módosíthatna, rejtett. Jelenítsd meg a testet, vagy válaszd az Új test lehetőséget.','two sides':'két oldal','Equal distance':'Egyenlő távolság','Two distances':'Két távolság','Distance and angle':'Távolság és szög',
    'Constant radius':'Állandó sugár','Variable radius':'Változó sugár','End radius':'Végsugár','Swap the two faces':'A két lap felcserélése','Type':'Típus',
    'Choose inside, outside or centered for the wall.':'Válaszd a fal helyzetét: belül, kívül vagy középen.','Choose one side, two sides or symmetric extrusion.':'Válassz egyoldali, kétoldali vagy szimmetrikus kihúzást.',
    'Two-sided extrusion needs the distance extent.':'A kétoldali kihúzáshoz távolság-kiterjedés kell.','The second distance cannot be zero.':'A második távolság nem lehet nulla.',
    'The wall thickness is too large for this profile.':'A falvastagság túl nagy ehhez a profilhoz.','The chamfer angle must be between 0 and 90 degrees.':'A letörés szögének 0 és 90 fok között kell lennie.',
    'The variable fillet cannot be built on these edges.':'A változó sugarú lekerekítés nem építhető fel ezeken az éleken.',
    'Standard size':'Szabványméret','Custom size':'Egyéni méret','Fit':'Illesztés','Clearance':'Átmenő furat','Tap drill':'Menetfúró átmérő','At the points of sketch':'A vázlat pontjain',
    'The selected sketch has no points to drill at. Add sketch points first.':'A kijelölt vázlatban nincs fúrási pont. Előbb adj hozzá vázlatpontokat.',
    'The sketch with the hole points is missing, suppressed or later in history.':'A furatpontokat tartalmazó vázlat hiányzik, el van nyomva vagy később van az előzményekben.',
    'Guide curve (optional)':'Vezetőgörbe (nem kötelező)','Use either a guide curve or Frenet orientation, not both.':'Használj vezetőgörbét vagy Frenet-tájolást, a kettőt együtt ne.',
    'This constraint requires a circle or an arc.':'Ehhez a kényszerhez kör vagy ív kell.','Pick two circles or arcs.':'Jelölj ki két kört vagy ívet.',
    'Pick a point, then a straight edge, circle or arc.':'Jelölj ki egy pontot, majd egy egyenes élt, kört vagy ívet.',
    'Pick two straight edges, or two circles / arcs.':'Jelölj ki két egyenes élt, vagy két kört / ívet.',
    'Pick a straight edge and a circle / arc, or two circles / arcs.':'Jelölj ki egy egyenes élt és egy kört / ívet, vagy két kört / ívet.',
    'Unknown expression parameter: ':'Ismeretlen kifejezés-paraméter: ','Duplicate parameter name: ':'Ismétlődő paraméternév: ','Duplicate dimension or parameter name: ':'Ismétlődő méret- vagy paraméternév: ',
    'Fully constrained':'Teljesen meghatározott',
}.items() if k not in HU})

_ERROR_TEMPLATES.extend([(re.compile(pattern,re.DOTALL),template) for pattern,template in (
    (r'Unknown expression parameter: (.+)','Ismeretlen kifejezés-paraméter: {}'),
    (r'Duplicate parameter name: (.+)','Ismétlődő paraméternév: {}'),
    (r'Duplicate dimension or parameter name: (.+)','Ismétlődő méret- vagy paraméternév: {}'),
    (r'Unknown (fillet|chamfer) mode\.','Ismeretlen {} mód.'),
)])


# Plain-language option names, tool steps, requirement hints and the sketch Extend / Offset / Transform tools.
HU.update({k:v for k,v in {
    # option names
    'One side':'Egy oldal','Symmetric':'Szimmetrikus','Two sides':'Két oldal','Distance':'Távolság','Through all':'Átmenő',
    'Up to a face or plane':'Egy lapig vagy síkig','Automatic (asks when it crosses a body)':'Automatikus (rákérdez, ha testet metsz)',
    'Join':'Egyesítés','Cut':'Kivágás','Intersect':'Metszet','New body':'Új test','Into the body':'A testbe befelé','Out of the body':'A testből kifelé',
    'Positive side':'Pozitív oldal','Negative side':'Negatív oldal','Both sides':'Mindkét oldal','Inside':'Belül','Outside':'Kívül','Centered':'Középre',
    'Features':'Műveletek','Faces':'Lapok','Whole bodies':'Teljes testek','Closed profile':'Zárt profil',
    'External (on a shaft)':'Külső (tengelyen)','Internal (in a hole)':'Belső (furatban)','All directions':'Minden irány','Along U':'U irányban','Along V':'V irányban',
    'Smooth through the points':'Sima a pontokon át','B-spline (control points)':'B-spline (vezérlőpontok)','Simple':'Egyszerű','Counterbore':'Süllyesztés (hengeres)',
    'Countersink':'Süllyesztés (kúpos)','Offset from a plane':'Eltolás egy síktól','At an angle to a plane':'Szögben egy síkhoz','Midway between two planes':'Két sík között középen',
    'Through three points':'Három ponton át','Rigid':'Merev','Revolute (hinge)':'Forgó (csukló)','Slider':'Csúszó','Cylindrical (slide and turn)':'Hengeres (csúszik és fordul)',
    'Mate (face to face)':'Illesztés (lap lapra)','Box':'Doboz','Cylinder':'Henger','Sphere':'Gömb','Cone':'Kúp','Torus':'Tórusz',
    'Vertical edges':'Függőleges élek','Top edges':'Felső élek','Bottom edges':'Alsó élek','Spacing between copies':'Másolatok közötti távolság','Overall length':'Teljes hossz',
    # tool titles
    'Rectangular pattern of features':'Műveletek téglalap alakú kiosztása','Circular pattern of features':'Műveletek körkiosztása','Mirror features':'Műveletek tükrözése',
    'Pattern along a path':'Kiosztás pálya mentén','Press / Pull':'Nyomás / Húzás','Offset face':'Lap eltolása','Split face':'Lap felosztása','Replace face':'Lap cseréje',
    'Primitive solid':'Alaptest','Extrude surface':'Felület kihúzása','Revolve surface':'Felület forgatása','Sweep surface':'Felület söprése','Loft surface':'Felület áthúzása',
    'Patch surface':'Felületfoltozás','Trim surface':'Felület vágása','Extend surface':'Felület meghosszabbítása','Stitch surfaces':'Felületek összevarrása','Thicken surface':'Felület vastagítása',
    # requirements
    'Still needed:':'Még szükséges:','a profile to revolve':'a forgatandó profil','an axis':'egy tengely','a profile':'egy profil','a path':'egy pálya',
    'at least two profiles, in order':'legalább két profil, sorrendben','the faces to draft':'a döntendő lapok','a neutral plane':'egy semleges sík',
    'a face or plane to drill from':'egy lap vagy sík, ahonnan fúrni kell','a reference plane or face':'egy referenciasík vagy lap','the second plane':'a második sík',
    'an axis, two points or a cylindrical face':'egy tengely, két pont vagy egy hengeres lap','the body to change':'a módosítandó test','the tool bodies':'a szerszámtestek',
    'the faces to push or pull':'a nyomandó vagy húzandó lapok','the body they belong to':'a test, amelyhez tartoznak','the body to scale':'a skálázandó test',
    'the body':'a test','the face to change':'a módosítandó lap','a splitting profile or curve':'egy felosztó profil vagy görbe','the replacement plane':'a cserélő sík',
    'the body to pattern':'a kiosztandó test','the features to repeat':'az ismétlendő műveletek','the faces to repeat':'az ismétlendő lapok','the target body':'a céltest',
    'the body to thread':'a menetezendő test','a cylindrical face':'egy hengeres lap','a cylindrical face or an axis':'egy hengeres lap vagy egy tengely',
    'a boundary curve or profile':'egy határgörbe vagy profil','at least two sections, in order':'legalább két metszet, sorrendben','the surface bodies':'a felülettestek',
    'a trim plane':'egy vágósík','the moving component':'a mozgó komponens','a face of the moving component':'a mozgó komponens egy lapja','the face to mate to':'a lap, amelyhez illeszteni kell',
    'the edges to round':'a lekerekítendő élek','the edges to bevel':'a letörendő élek','a profile':'egy profil',
    # tool steps
    'Click a profile or a flat face, then drag the arrow or type the distance. Apply keeps the result.':'Kattints egy profilra vagy sík lapra, majd húzd a nyilat vagy írd be a távolságot. Az Alkalmaz megtartja az eredményt.',
    'Click the profile, choose the axis it turns around (an edge of the profile is best), set the angle.':'Kattints a profilra, válaszd ki a tengelyt, amely körül forog (a profil egy éle a legjobb), és add meg a szöget.',
    'Click the profile, then the path. The profile should sit at the start of the path, square to it.':'Kattints a profilra, majd a pályára. A profilnak a pálya elején kell lennie, merőlegesen rá.',
    'Click the profiles in the order the shape should pass through them (at least two).':'Kattints a profilokra abban a sorrendben, ahogy az alaknak át kell haladnia rajtuk (legalább kettő).',
    'Click the faces to leave open (or none for a closed hollow), then set the wall thickness and side.':'Kattints a nyitva hagyandó lapokra (vagy egyre sem a zárt üreghez), majd add meg a falvastagságot és az oldalt.',
    'Click the faces to tilt, choose the neutral plane (the plane that stays put), then set the angle.':'Kattints a döntendő lapokra, válaszd ki a semleges síkot (amely helyben marad), majd add meg a szöget.',
    'Click the face to drill from, set the position, size and depth. Choose a standard screw size to fill in the diameter.':'Kattints a lapra, ahonnan fúrsz, add meg a helyzetet, méretet és mélységet. Szabványos csavarméret választásával kitöltődik az átmérő.',
    'Click the edges to round (a tangent chain is taken together), then drag the arrow or type the radius.':'Kattints a lekerekítendő élekre (az érintkező lánc együtt kerül kijelölésre), majd húzd a nyilat vagy írd be a sugarat.',
    'Click the edges to bevel, choose the type, then drag the arrow or type the distance.':'Kattints a letörendő élekre, válaszd ki a típust, majd húzd a nyilat vagy írd be a távolságot.',
    'Choose how the plane is defined, then click its reference. Use it as a sketch plane afterwards.':'Válaszd ki, hogyan van meghatározva a sík, majd kattints a referenciájára. Utána vázlatsíkként használhatod.',
    'Click two points, or a round face, to place an axis for revolves and patterns.':'Kattints két pontra vagy egy kerek lapra, hogy tengelyt helyezz el forgatáshoz és kiosztáshoz.',
    'Click the body, then drag the arrows or type the distances and the rotation. Tick copy to keep the original.':'Kattints a testre, majd húzd a nyilakat vagy írd be a távolságokat és a forgatást. A másolás megtartja az eredetit.',
    'Click the body, choose the mirror plane. Keep originals gives you both halves.':'Kattints a testre, válaszd ki a tükörsíkot. Az eredetiek megtartásával mindkét fél megmarad.',
    'Click the body, choose the plane, then set the counts and the spacing (or the overall length).':'Kattints a testre, válaszd ki a síkot, majd add meg a darabszámot és a távolságot (vagy a teljes hosszat).',
    'Click the body, choose the axis, then set the number of positions and the angle.':'Kattints a testre, válaszd ki a tengelyt, majd add meg a pozíciók számát és a szöget.',
    'Click the body, choose the plane that cuts it, and which side to keep.':'Kattints a testre, válaszd ki a metsző síkot és azt, hogy melyik oldal maradjon.',
    'Click the body to keep (target), then the tool bodies. Join, Cut or Intersect decides the result.':'Kattints a megtartandó testre (cél), majd a szerszámtestekre. Az Egyesítés, Kivágás vagy Metszet dönti el az eredményt.',
    'Click a face and type how far to push it in or pull it out. A profile can add or cut material.':'Kattints egy lapra, és írd be, mennyivel nyomd be vagy húzd ki. Egy profil anyagot adhat hozzá vagy vághat ki.',
    'Click the body, set the factor and the point it scales about.':'Kattints a testre, add meg a tényezőt és azt a pontot, amely körül skálázódik.',
    'Click the faces to move, then type the offset distance (negative moves them inward).':'Kattints a mozgatandó lapokra, majd írd be az eltolás távolságát (a negatív befelé mozgatja).',
    'Click the face to divide, then choose the sketch profile or curve that divides it.':'Kattints a felosztandó lapra, majd válaszd ki a felosztó vázlatprofilt vagy görbét.',
    'Click the faces to replace, then choose the plane they should move to.':'Kattints a cserélendő lapokra, majd válaszd ki a síkot, ahová mozogjanak.',
    'Choose the feature to repeat, click the body, then set columns, rows and spacing.':'Válaszd ki az ismétlendő műveletet, kattints a testre, majd add meg az oszlopokat, sorokat és a távolságot.',
    'Choose the feature to repeat, click the body, choose the axis and set the number of positions.':'Válaszd ki az ismétlendő műveletet, kattints a testre, válaszd ki a tengelyt és add meg a pozíciók számát.',
    'Choose the feature to mirror, click the body, choose the mirror plane.':'Válaszd ki a tükrözendő műveletet, kattints a testre, válaszd ki a tükörsíkot.',
    'Choose the feature, click the body, then click the curve it should be repeated along.':'Válaszd ki a műveletet, kattints a testre, majd arra a görbére, amely mentén ismételni kell.',
    'Choose the shape and its size. New body adds a separate body; Join/Cut combines it with a target.':'Válaszd ki az alakot és a méretét. Az Új test külön testet ad hozzá; az Egyesítés/Kivágás egy céltesttel kombinálja.',
    'Click the path curve, then set the diameter. Hollow gives a tube with the wall thickness you set.':'Kattints a pályagörbére, majd add meg az átmérőt. Az Üreges a megadott falvastagságú csövet ad.',
    'Click the sketch line the rib stands on, then set thickness and height.':'Kattints a vázlatvonalra, amelyen a borda áll, majd add meg a vastagságot és a magasságot.',
    'Click the sketch line, then set thickness and height; the wall is centred on the sketch plane.':'Kattints a vázlatvonalra, majd add meg a vastagságot és a magasságot; a fal a vázlatsíkra van középre igazítva.',
    'Click the round wall of a shaft or hole. Pitch and thread depth set the groove.':'Kattints egy tengely vagy furat kerek falára. A menetemelkedés és a menetmélység adja a hornyot.',
    'Click a round face (or choose an axis), then set the pitch, height and wire diameter.':'Kattints egy kerek lapra (vagy válassz tengelyt), majd add meg a menetemelkedést, magasságot és huzalátmérőt.',
    'Click a curve or profile, then type the extrusion vector.':'Kattints egy görbére vagy profilra, majd írd be a kihúzás vektorát.','Click a curve, choose the axis, set the angle.':'Kattints egy görbére, válaszd ki a tengelyt, add meg a szöget.',
    'Click the boundary curve, then the path.':'Kattints a határgörbére, majd a pályára.','Add the section curves in order (at least two).':'Add hozzá a metszetgörbéket sorrendben (legalább kettő).',
    'Click a closed boundary: the surface fills it.':'Kattints egy zárt határra: a felület kitölti.','Choose the surface bodies and the plane that cuts them; pick the side to keep.':'Válaszd ki a felülettesteket és a vágósíkot; add meg a megtartandó oldalt.',
    'Choose the surface and how far to extend it.':'Válaszd ki a felületet és azt, mennyivel hosszabbítsd meg.','Choose the surfaces to sew together; tick Make solid for a closed shell.':'Válaszd ki az összevarrandó felületeket; a Tömör test létrehozása zárt héjat ad.',
    'Choose the surface and the thickness to give it.':'Válaszd ki a felületet és a vastagságot.','Name the component and place it. Edit its history to model the part inside it.':'Nevezd el a komponenst és helyezd el. Az előzményeinek szerkesztésével modellezheted benne az alkatrészt.',
    'Choose the moving component and how it connects. Mate puts one face against another.':'Válaszd ki a mozgó komponenst és a kapcsolat módját. Az Illesztés egy lapot egy másikhoz illeszt.',
    'Drag the arrows or type how far the sketch moves.':'Húzd a nyilakat vagy írd be, mennyivel mozduljon a vázlat.','Click points in the view to build 3D curves; Enter finishes a curve.':'Kattints pontokra a nézetben 3D görbék építéséhez; az Enter lezár egy görbét.',
    'Click a face, then click points on it to draw curves that follow the surface.':'Kattints egy lapra, majd pontokra rajta, hogy a felületet követő görbéket rajzolj.',
    # new panel texts
    'Reverse direction':'Irány megfordítása','Extrude to the other side of the sketch plane or face.':'Kihúzás a vázlatsík vagy lap másik oldalára.',
    'Symmetric (half the angle on each side)':'Szimmetrikus (a szög fele mindkét oldalra)','Wall thickness':'Falvastagság','Wall side':'Fal oldala','Inside the body':'A testen belül','Outside the body':'A testen kívül',
    'Drill point angle (0 = flat bottom)':'Fúrócsúcs szöge (0 = lapos fenék)','118° is a standard twist-drill point.':'A 118° a szabványos csigafúró-csúcs.',
    'Use the axis of a round face':'Kerek lap tengelyének használata','Click two points instead':'Inkább két pont kijelölése','That face is not round. Click the wall of a shaft or a round hole.':'Ez a lap nem kerek. Kattints egy tengely vagy kerek furat falára.',
    'Distance type':'Távolság típusa','Select all edges':'Összes él kijelölése','Clear selection':'Kijelölés törlése',
    'Add constraints while drawing':'Kényszerek hozzáadása rajzolás közben','Joins end points that land on other geometry and makes near-horizontal or vertical lines exact.':'Összekapcsolja a más geometriára eső végpontokat, és pontossá teszi a közel vízszintes vagy függőleges vonalakat.',
    # sketch tools
    'Extend':'Meghosszabbítás','Offset':'Eltolás (párhuzamos)','Transform':'Átalakítás','Move / Rotate / Scale':'Mozgatás / Forgatás / Skálázás','Modify':'Módosítás',
    'Click a line or arc near the end you want to lengthen: it runs on to the next curve it meets.':'Kattints egy vonalra vagy ívre a meghosszabbítandó vége közelében: a következő görbéig fut.',
    'Click the curves to offset (a connected chain is taken as it is), then set the distance. Positive grows a closed outline.':'Kattints az eltolandó görbékre (az összefüggő lánc egészében számít), majd add meg a távolságot. A pozitív érték növeli a zárt körvonalat.',
    'Click the geometry to change, choose Move, Rotate or Scale, and type the values. Copy keeps the original.':'Kattints a módosítandó geometriára, válaszd a Mozgatás, Forgatás vagy Skálázás műveletet, és írd be az értékeket. A másolás megtartja az eredetit.',
    'item selected':'elem kijelölve','items selected':'elem kijelölve','click geometry to add or remove it; Shift+drag draws a selection box.':'kattints a geometriára a hozzáadáshoz vagy eltávolításhoz; Shift+húzás kijelölő dobozt rajzol.',
    'Create offset':'Eltolás létrehozása','Other side':'Másik oldal','Operation':'Művelet','Move':'Mozgatás','Rotate':'Forgatás','Scale':'Skálázás','Distance X':'X távolság','Distance Y':'Y távolság',
    'Center X':'Középpont X','Center Y':'Középpont Y','Angle':'Szög','Scale factor':'Skálázási tényező','Use the center of the selection':'A kijelölés közepének használata',
    'Copy (keep the original)':'Másolás (az eredeti megmarad)','Apply transform':'Átalakítás alkalmazása','Done':'Kész','curves created. Undo reverses the offset.':'görbe létrejött. A visszavonás megfordítja az eltolást.',
    'Transformed.':'Átalakítva.','constraints on the moved geometry were removed.':'kényszer a mozgatott geometrián eltávolítva.',
    'Nothing lies in the way: this end does not reach another curve.':'Semmi sincs az útban: ez a vég nem ér el másik görbét.','Click a line or arc near the end you want to extend.':'Kattints egy vonalra vagy ívre a meghosszabbítandó vége közelében.',
    'Extend works on lines and arcs.':'A meghosszabbítás vonalakra és ívekre működik.','This line has no length to extend.':'Ennek a vonalnak nincs hossza a meghosszabbításhoz.',
    'The extension would close the arc into a full circle. Use a circle instead.':'A meghosszabbítás teljes körré zárná az ívet. Használj inkább kört.',
    'Enter an offset distance other than zero.':'Adj meg nullától különböző eltolási távolságot.','Select the curves to offset.':'Jelöld ki az eltolandó görbéket.',
    'The offset is larger than an arc of the outline. Use a smaller distance.':'Az eltolás nagyobb a körvonal egyik ívénél. Használj kisebb távolságot.',
    'The offset is larger than the circle. Use a smaller distance.':'Az eltolás nagyobb a körnél. Használj kisebb távolságot.','The offset produced no geometry.':'Az eltolás nem hozott létre geometriát.',
    'Offset works on lines, arcs, circles, rectangles, polygons and slots.':'Az eltolás vonalakra, ívekre, körökre, téglalapokra, sokszögekre és hornyokra működik.',
    'Select the geometry to transform.':'Jelöld ki az átalakítandó geometriát.','Enter a distance to move.':'Adj meg mozgatási távolságot.','Enter an angle other than zero.':'Adj meg nullától különböző szöget.',
    'The scale factor must be a positive number.':'A skálázási tényezőnek pozitív számnak kell lennie.','Choose move, rotate or scale.':'Válaszd a mozgatást, forgatást vagy skálázást.',
    'The revolve axis passes through the profile. Put the axis on an edge of the profile or outside it, or sketch only half of the shape.':'A forgatási tengely átmegy a profilon. Tedd a tengelyt a profil egyik élére vagy kívülre, vagy csak az alak felét rajzold meg.',
    'The drill point angle must be between 0 and 180 degrees.':'A fúrócsúcs szögének 0 és 180 fok között kell lennie.',
}.items() if k not in HU})


# Click-to-choose inputs (pick_slots).
HU.update({k:v for k,v in {
    'Profile to revolve':'Forgatandó profil','Axis it turns around':'Tengely, amely körül forog','Profile':'Profil','Path':'Pálya','Guide curve (optional)':'Vezetőgörbe (nem kötelező)',
    'Profiles, in order':'Profilok sorrendben','Faces to leave open (none = closed hollow)':'Nyitva hagyandó lapok (egy sem = zárt üreg)','Faces to draft':'Döntendő lapok',
    'Neutral plane (stays put)':'Semleges sík (helyben marad)','Click where the hole goes':'Kattints oda, ahová a furat kerül','Plane or face to start from':'Kiinduló sík vagy lap',
    'Axis to tilt about':'Tengely, amely körül dől','First plane or face':'Első sík vagy lap','Second plane or face':'Második sík vagy lap','Edge, round face or sketch line':'Él, kerek lap vagy vázlatvonal',
    'Body to keep (target)':'Megtartandó test (cél)','Bodies to combine with it':'Vele kombinálandó testek','Body':'Test','Mirror plane':'Tükörsík','Plane the copies lie in':'A másolatok síkja',
    'Plane that cuts the body':'A testet metsző sík','Axis to turn about':'Tengely, amely körül fordul','Axis for the rotation (optional)':'Tengely a forgatáshoz (nem kötelező)',
    'Faces to push or pull':'Nyomandó vagy húzandó lapok','Body to change':'Módosítandó test','Faces to move':'Mozgatandó lapok','Body to scale':'Skálázandó test',
    'Face to divide':'Felosztandó lap','Profile or curve that divides it':'A felosztó profil vagy görbe','Faces to replace':'Cserélendő lapok','Plane they move to':'A sík, ahová mozognak',
    'Click a face made by the feature to repeat':'Kattints az ismétlendő művelet által készített lapra','Faces to repeat':'Ismétlendő lapok','Plane of the pattern':'A kiosztás síkja',
    'Sketch line':'Vázlatvonal','Round face (shaft or hole wall)':'Kerek lap (tengely vagy furat fala)','Boundary curve or profile':'Határgörbe vagy profil','Curve or profile':'Görbe vagy profil',
    'Curves, in order':'Görbék sorrendben','Surfaces':'Felületek','Plane that trims':'A vágó sík','Face of the part that moves':'A mozgó alkatrész egy lapja','Face it should touch':'A lap, amelyhez érnie kell',
    'Part that moves':'Mozgó alkatrész','Part it is attached to (none = the origin)':'Alkatrész, amelyhez kapcsolódik (egy sem = az origó)',
    'click it in the 3D view':'kattints rá a 3D nézetben','chosen':'kiválasztva','default, click to change':'alapértelmezett, kattints a módosításhoz','Next':'Tovább',
    'Done choosing here: go to the next input.':'Itt kész a választás: tovább a következő bemenethez.','Clear':'Törlés','Use the':'Használd:',
    'Click here, then click the object in the 3D view.':'Kattints ide, majd az objektumra a 3D nézetben.','Show all selection options':'Összes kijelölési lehetőség megjelenítése',
    'The lists and drop-down menus behind the clicks: for choosing something you cannot click.':'A kattintások mögötti listák és legördülők: olyasmi kiválasztásához, amire nem lehet kattintani.',
    'Nothing there. Click':'Ott nincs semmi. Kattints erre:','in the 3D view.':'a 3D nézetben.',
    'Click to choose this face':'Kattints ennek a lapnak a kiválasztásához','Click to choose this plane':'Kattints ennek a síknak a kiválasztásához',
    'Click to choose this construction plane':'Kattints ennek a segédsíknak a kiválasztásához','Click to choose this profile':'Kattints ennek a profilnak a kiválasztásához',
    'Click to choose this curve':'Kattints ennek a görbének a kiválasztásához','Click to choose this edge':'Kattints ennek az élnek a kiválasztásához',
    'Click a closed sketch profile or a flat face.':'Kattints egy zárt vázlatprofilra vagy sík lapra.','That face is curved. Click a closed sketch profile or a flat face.':'Ez a lap ívelt. Kattints egy zárt vázlatprofilra vagy sík lapra.',
    'Click one of the sketch curves.':'Kattints az egyik vázlatgörbére.','That face is curved. Click a flat face or one of the planes.':'Ez a lap ívelt. Kattints egy sík lapra vagy az egyik síkra.',
    'Click a flat face or a plane.':'Kattints egy sík lapra vagy egy síkra.','Click a face of the body.':'Kattints a test egy lapjára.','Click a body.':'Kattints egy testre.',
    'That face does not belong to a body of the model.':'Ez a lap nem tartozik a modell egyik testéhez sem.','Click a face that the feature created.':'Kattints egy lapra, amelyet a művelet hozott létre.',
    'Could not tell which feature made that face. Try another of its faces, or use "Show all selection options".':'Nem állapítható meg, melyik művelet hozta létre ezt a lapot. Próbáld a művelet egy másik lapját, vagy használd az „Összes kijelölési lehetőség megjelenítése” opciót.',
    'Click a body of the part.':'Kattints az alkatrész egy testére.','Click a flat face.':'Kattints egy sík lapra.','Click a surface.':'Kattints egy felületre.','That is not a surface body.':'Ez nem felülettest.',
    'That face is not round. Click the wall of a shaft or a round hole.':'Ez a lap nem kerek. Kattints egy tengely vagy kerek furat falára.','Click a flat face to drill from.':'Kattints egy sík lapra, ahonnan fúrni kell.',
    'This input cannot be picked with a click.':'Ez a bemenet nem választható kattintással.',
    'An axis needs a straight line. Click a straight sketch line, a straight edge or a round face.':'A tengelyhez egyenes vonal kell. Kattints egy egyenes vázlatvonalra, egyenes élre vagy kerek lapra.',
    'That edge is curved. Click a straight edge, a circular edge or a round face.':'Ez az él ívelt. Kattints egy egyenes élre, kör alakú élre vagy kerek lapra.',
    'Click a round face, a flat face (its normal), a straight edge or a sketch line.':'Kattints egy kerek lapra, sík lapra (a normálisa), egyenes élre vagy vázlatvonalra.',
    'Click a straight edge, a round face or a sketch line.':'Kattints egy egyenes élre, kerek lapra vagy vázlatvonalra.',
    'Click a body that belongs to a component.':'Kattints egy komponenshez tartozó testre.','That body is not part of a component. Make a component first.':'Ez a test nem része komponensnek. Előbb hozz létre komponenst.',
    'Axis through two points':'Két ponton átmenő tengely','Construction plane':'Segédsík','line':'vonal','curve':'görbe','profile':'profil','plane':'sík','axis':'tengely',
}.items() if k not in HU})


# SpaceMouse settings.
HU.update({k:v for k,v in {
    'SpaceMouse…':'SpaceMouse…','Settings · SpaceMouse':'Beállítások · SpaceMouse',
    'SpaceMouse support is not available on this system.':'A SpaceMouse támogatás nem érhető el ezen a rendszeren.',
    'Listening for a 3Dconnexion device.':'3Dconnexion eszközt figyelek.',
    'No SpaceMouse input found (Linux needs the spacenavd daemon).':'Nem található SpaceMouse bemenet (Linuxon a spacenavd szolgáltatás kell).',
    'Use the SpaceMouse to move the view':'SpaceMouse használata a nézet mozgatásához','Rotation speed':'Forgatás sebessége','Pan speed':'Eltolás sebessége',
    'Zoom speed':'Nagyítás sebessége','Dead zone':'Holtsáv','Dominant axis only (one movement at a time)':'Csak a domináns tengely (egyszerre egy mozgás)',
    'Press a button on the device to assign it.':'Nyomj meg egy gombot az eszközön a hozzárendeléshez.','(nothing)':'(semmi)','Button':'Gomb',
    'Calibrate axes…':'Tengelyek kalibrálása…','SpaceMouse axes calibrated.':'A SpaceMouse tengelyei kalibrálva.',
    'Fit view':'Nézet illesztése','Iso view':'Izometrikus nézet','Top view':'Felülnézet','Front view':'Elölnézet','Right view':'Jobb nézet',
    'Apply':'Alkalmaz','Undo':'Visszavonás','Redo':'Újra','Toggle grid':'Rács kapcsolása',
    'Push the cap to the right':'Told a kupakot jobbra','Push the cap forward, away from you':'Told a kupakot előre, magadtól el',
    'Lift the cap straight up':'Emeld fel a kupakot egyenesen','Tilt the cap forward':'Döntsd előre a kupakot',
    'Twist the cap clockwise (seen from above)':'Csavard a kupakot az óramutató járásával megegyezően (felülről nézve)',
    'the model moves right':'a modell jobbra mozdul','the model moves up':'a modell felfelé mozdul','the view zooms in':'a nézet nagyít',
    'the model tips forward':'a modell előre billen','the model turns clockwise':'a modell az óramutató irányába fordul',
}.items() if k not in HU})

HU.update({k:v for k,v in {
    'Active':'Aktív','Reverse':'Fordított','Reverse all axes':'Minden tengely megfordítása','Push left / right':'Tolás balra / jobbra',
    'Push forward / back':'Tolás előre / hátra','Lift / press (zoom)':'Emelés / nyomás (nagyítás)','Tilt forward / back':'Döntés előre / hátra',
    'Roll left / right':'Dőlés balra / jobbra','Twist (spin)':'Csavarás (forgatás)',
}.items() if k not in HU})

HU.update({k:v for k,v in {'Lock rotation':'Forgatás zárolása','Rotation locked':'Forgatás zárolva','Rotation free':'Forgatás szabad'}.items() if k not in HU})

HU.update({k:v for k,v in {'Rotate only':'Csak forgatás','Turn 90°':'Elforgatás 90°-kal','Only rotating':'Csak forgatás','Pan, zoom and rotate':'Eltolás, nagyítás és forgatás'}.items() if k not in HU})

HU.update({'Update available':'Frissítés elérhető','SlothCAD {new} is available (you have {old}). Click to install it and restart.':'Elérhető a SlothCAD {new} (jelenleg: {old}). Kattints a telepítéshez és az újraindításhoz.','Update SlothCAD':'SlothCAD frissítése','Install SlothCAD {new} now? The changed files are downloaded from GitHub and SlothCAD restarts. You are asked to save unsaved projects first.':'Telepíted most a SlothCAD {new} verziót? A módosult fájlok letöltődnek a GitHubról, majd a SlothCAD újraindul. Előtte rákérdez a nem mentett projektek mentésére.','Downloading update…':'Frissítés letöltése…','Comparing files…':'Fájlok összehasonlítása…','Installing new Python packages…':'Új Python-csomagok telepítése…','Installing update…':'Frissítés telepítése…','Update installed.':'Frissítés telepítve.','SlothCAD is already up to date.':'A SlothCAD már naprakész.','The update is installed. It takes effect the next time SlothCAD starts.':'A frissítés telepítve. A SlothCAD következő indításakor lép életbe.'})

HU.update({k:v for k,v in {'Import…':'Importálás…','Export…':'Exportálás…','Import':'Importálás','Export':'Exportálás','Choose a file type:':'Válassz fájltípust:','Continue':'Tovább',
    'IGES solid (*.iges *.igs)':'IGES test (*.iges *.igs)','OBJ mesh (*.obj)':'OBJ háló (*.obj)','DXF sketch (*.dxf)':'DXF vázlat (*.dxf)','Drawing (*.dxf *.svg)':'Rajz (*.dxf *.svg)',
    'Exact solid bodies with names and colours':'Pontos testek nevekkel és színekkel','Closed triangle mesh, converted to a solid':'Zárt háromszögháló, testté alakítva',
    'Older exact CAD format':'Régebbi pontos CAD-formátum','3D-printing package, converted to a solid':'3D-nyomtatási csomag, testté alakítva','2D geometry, imported as a sketch':'2D geometria, vázlatként importálva',
    'Exact solids for other CAD programs':'Pontos testek más CAD-programokhoz','Triangle mesh for 3D printing':'Háromszögháló 3D-nyomtatáshoz','3D-printing package with colours':'3D-nyomtatási csomag színekkel',
    'Mesh for viewers, web and rendering':'Háló megjelenítőkhöz, webhez és rendereléshez','The selected or current sketch as 2D geometry':'A kijelölt vagy aktuális vázlat 2D geometriaként',
    'Projected 2D views of the model':'A modell vetített 2D nézetei','Bring in a STEP, STL or DXF file':'STEP, STL vagy DXF fájl behozása'}.items() if k not in HU})

HU.update({k:v for k,v in {'Importing':'Importálás','Starting…':'Indítás…','Elapsed:':'Eltelt idő:','Import cancelled.':'Importálás megszakítva.','Imported':'Importálva',
    'Adding it to the model…':'Hozzáadás a modellhez…','Starting the CAD kernel…':'A CAD-mag indítása…','Reading mesh file…':'Hálófájl beolvasása…',
    'Building {count} triangles…':'{count} háromszög felépítése…','Sewing {count} triangles into a solid…':'{count} háromszög összevarrása testté…',
    'Checking geometry…':'Geometria ellenőrzése…','Packing geometry…':'Geometria tömörítése…','Reading STEP file…':'STEP-fájl beolvasása…',
    'Reading STEP shapes…':'STEP-alakzatok beolvasása…','Reading IGES file…':'IGES-fájl beolvasása…','Sewing {count} surfaces…':'{count} felület összevarrása…',
    'The import stopped unexpectedly.':'Az importálás váratlanul leállt.'}.items() if k not in HU})

HU.update({k:v for k,v in {'Computing mass properties…':'Tömegtulajdonságok számítása…','Preparing export…':'Exportálás előkészítése…','Reading shapes…':'Alakzatok beolvasása…',
    'Writing STEP file…':'STEP-fájl írása…','Writing STL file…':'STL-fájl írása…','Writing 3MF file…':'3MF-fájl írása…','Writing GLB file…':'GLB-fájl írása…',
    'Projecting views…':'Nézetek vetítése…','Checking interference…':'Ütközés ellenőrzése…',
    'The background CAD process stopped unexpectedly. Please try again.':'A háttérben futó CAD-folyamat váratlanul leállt. Próbáld újra.'}.items() if k not in HU})
