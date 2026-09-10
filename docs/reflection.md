# Reflektionsdokument

## 1. Varför ska sensorerna kommunicera med ett API i stället för direkt med PostgreSQL?

För att det finns saker som måste hända med datan innan den får sparas, och de
sakerna hör hemma på ett ställe.

I den här lösningen gör API:t tre kontroller som databasen inte kan göra åt
mig: att temperaturen är ett tal och inte strängen `"ERROR"`, att värdena
ligger inom rimliga mätområden, och att `deviceId` tillhör en sensor jag känner
till. Sensor-003 skickar med flit trasig data ibland, och den datan blir stoppad
på ett ställe oavsett hur många sensorer som finns.

Det handlar också om åtkomst. Skulle sensorerna prata direkt med databasen
behövde var och en ha databasinloggning, och då kan de i praktiken göra vad som
helst mot den. Nu har de bara en HTTP-endpoint att posta till.

Sedan är det praktiskt när något ska ändras. När jag lade till cachen behövde
jag inte röra simulatorn alls. Den postar likadant som förut, och API:t gör
något mer med datan på insidan.

## 2. Varför ska felaktig sensordata stoppas innan den sparas?

För att felaktig data som väl kommit in är mycket svårare att bli av med än att
avvisa den direkt.

Ett konkret exempel från labben: `AVG(temperature)` över alla mätningar. Hade
en enda rad med 5000 grader kommit in hade medelvärdet varit fel, och det syns
inte förrän någon undrar varför siffran ser konstig ut. Då ska man gå tillbaka
och lista ut vilka rader som är skräp, vilket är en helt annan sak än att ha
sagt nej från början.

Sedan är det ärligare mot avsändaren. Sensorn får `400` och en förklaring
direkt, i stället för `201` på något som egentligen inte gick att använda.

Jag hittade också ett fall som inte var uppenbart. Starterkoden kontrollerade
batterinivån med `isinstance(value, int)`, och i Python är `isinstance(True, int)`
sant eftersom `bool` ärver från `int`. Det betyder att `{"battery": true}` hade
passerat valideringen och sparats som talet 1. Jag fick stänga ute `bool`
explicit.

## 3. Varför passar PostgreSQL för historiska mätvärden?

Mätvärden är strukturerade och likadana varje gång. Varje rad har sensor,
temperatur, luftfuktighet, batterinivå och en tidsstämpel. Det passar en tabell
med kolumner bra.

Frågorna jag faktiskt vill ställa är också precis det en relationsdatabas är
byggd för. `COUNT`, `AVG`, gruppering per sensor och filtrering på tidsintervall
är inbyggt. Frågan som tar fram vilken sensor som är varmast är fem rader SQL,
och den räknas ut där datan redan finns i stället för att jag hämtar ut allt och
räknar i Python.

Databasen bevakar dessutom sammanhanget åt mig. `measurements.device_id` har en
främmande nyckel mot `devices`, så det går inte att spara en mätning från en
sensor som inte finns. Även om jag glömde kontrollen i API-koden skulle
databasen säga ifrån.

Och så överlever datan. Den ligger i volymen `postgres_data`, som är fristående
från containern. Jag verifierade det: 945 mätningar före `docker compose down`
och 945 efter att miljön startats igen, och raden med id 991 gick att hämta ut
precis som förut.

## 4. Vad händer med lösningen om Redis försvinner?

Ingenting går förlorat. Det blir långsammare, och det är hela skillnaden.

Cachen innehåller bara en kopia av något som redan finns i PostgreSQL, nämligen
varje sensors senaste mätning. Försvinner Redis blir varje läsning av
`/devices/<id>/latest` en cache miss, går till databasen i stället och fyller på
cachen igen.

Jag testade det på två sätt. Med `FLUSHDB` försvann alla nycklar, och nästa
anrop svarade `"source": "database"` med rätt värde och la tillbaka nyckeln. Vid
persistence-kontrollen togs hela Redis-containern bort, och efter omstarten var
cachen tom tills första läsningen byggde upp den igen.

Det där kommer inte gratis. Jag fick fånga alla Redis-fel inne i `cache.py` och
låta dem bli en cache miss i stället för att kastas vidare. Utan det hade ett
nedsläckt Redis gett `500` på en endpoint som mycket väl hade kunnat svara med
data från databasen.

## 5. Vad händer med lösningen om PostgreSQL försvinner?

Då slutar lösningen fungera på riktigt, och till skillnad från Redis går data
förlorad.

Nya mätningar går inte att spara, så allt som sensorerna skickar under tiden är
borta för alltid. Historiken går inte att läsa. Det enda som fortfarande skulle
kunna besvaras är läsningar av senaste värdet som råkar ligga kvar i cachen, och
bara tills TTL:en på fem minuter löper ut.

Skillnaden mot Redis är att PostgreSQL är den enda platsen där datan finns. Det
gör den till lösningens verkliga svaga punkt. I den här labben körs den som en
ensam container med en volym, vilket räcker för ändamålet men inte hade räckt i
skarp drift. Där hade det behövts säkerhetskopior och antagligen replikering.

API:t svarar i alla fall vettigt när det händer. Databasfel fångas och blir
`503 database unavailable` i JSON, inte en Flask-felsida.

## 6. Varför används Docker Compose lokalt?

För att hela miljön ska gå att starta med ett kommando och se likadan ut varje
gång.

Lösningen består av fyra delar som behöver varandra: databasen, cachen, API:t
och simulatorn. Utan Compose hade jag fått installera PostgreSQL och Redis på
datorn, se till att versionerna stämmer, starta dem i rätt ordning och komma
ihåg hur allt hänger ihop. Nu ligger det i en fil.

Beroendena är beskrivna i filen och inte något jag behöver hålla i huvudet.
API:t väntar på att databasen ska bli `healthy` innan det startar, tack vare
`depends_on` med `condition: service_healthy`. Containrarna hittar varandra på
tjänstenamn, så API:t ansluter till värdnamnet `db` utan att någon IP-adress
behöver vara inblandad.

Det som gjorde mest skillnad i praktiken var att kunna riva och starta om.
`docker compose down` följt av `up -d` tar ett par sekunder, och volymen ser
till att databasen inte börjar om från noll.

## 7. Vad automatiserar din CI-pipeline?

Den kör vid varje push och vid varje pull request och gör fyra saker: hämtar
koden, installerar beroenden från `api/requirements.txt`, kör hela testsviten
och bygger API:ts Docker image.

Jag lade till två saker utöver det minsta.

Testerna körs mot en riktig PostgreSQL och en riktig Redis, som startas som
service-containrar med samma images som i `docker-compose.yml`. Det var
nödvändigt. Mina integrationstester hoppar över sig själva när databasen inte
går att nå, så utan tjänsterna hade CI blivit grön efter att ha kört bara
enhetstesterna för valideringen. En grön körning som inte testat något är värre
än ingen körning alls, för den ser ut som ett besked.

Sista steget startar den image som just byggts och kontrollerar att `/health`
svarar. Att en image byggde säger inte att den går att köra. Ett stavfel i
`CMD` eller ett saknat beroende syns först när containern startar.

## 8. Vad observerade du när du tog bort en Kubernetes Pod?

Att Poden inte kom tillbaka, men att antalet gjorde det.

Jag raderade `jensen-iot-api-7b9fbb47d4-g9qxd`. En sekund senare visade
`kubectl get pods` att den var `Terminating`, och samtidigt fanns en ny Pod med
namnet `...-wxc9t` i status `ContainerCreating`. Efter några sekunder var den
`Running` och `1/1`. Den raderade Poden var borta och kom aldrig igen.

Det som förvånade mig var timingen. Ersättaren skapades direkt när raderingen
begärdes, alltså medan den gamla Poden fortfarande höll på att stänga ner. Det
var inte så att en Pod försvann och att Kubernetes upptäckte det efteråt.
Antalet fungerande Pods hann därför aldrig gå under tre.

Det fick mig att förstå vad self-healing faktiskt betyder här. Kubernetes lagar
inte den trasiga Poden. Det som hålls vid liv är antalet repliker.
Deploymenten säger tre, ReplicaSet:et räknar och skapar nya tills det stämmer.
Poddar är utbytbara, och namnen ändras varje gång.

Samma mekanism syntes vid skalningen. `kubectl scale --replicas=5` ändrar bara
en siffra i Deploymenten, och två nya Pods dök upp inom en sekund. Vid
nedskalning till tre gick två över i `Terminating`.

## 9. Varför kan flera repliker ge högre tillgänglighet?

För att en Pod kan försvinna utan att tjänsten gör det.

Det bygger på att Servicen inte pekar på en viss Pod utan väljer Pods på
etiketten `app=jensen-iot-api`. När en Pod försvinner tas den ur listan, och när
en ny blir klar läggs den till. Den som anropar Servicen märker ingenting och
behöver inte känna till några Pod-namn eller IP-adresser.

Jag såg lastfördelningen genom att anropa Servicen inifrån klustret. Anropen
landade på olika Pods, och `/health` returnerar Podens namn så det gick att se
direkt i svaret. Via `kubectl port-forward` såg det däremot ut som att allt gick
till samma Pod, vilket det också gjorde. Port-forward mot en Service binder till
en enda Pod och lastbalanserar inte, så det är fel verktyg för att visa det här.

Tydligast blev det under rolling update. Jag lät en separat Pod anropa Servicen
två gånger per sekund medan jag rullade ut version `lab-v2` och sedan rullade
tillbaka. 200 anrop, noll misslyckade. Versionsfältet i svaren gick från `lab`
till `lab-v2` och tillbaka mitt under trafiken. Två saker gjorde det möjligt:
`maxUnavailable: 0`, som ser till att en ny Pod startar innan en gammal tas
bort, och readinessProbe, som håller nystartade Pods utanför Servicen tills de
faktiskt svarar.

Flera repliker skyddar däremot inte mot allt. Alla tre kör på samma nod i
Minikube, så går noden ner går alla med. Och delen som verkligen inte tål att
försvinna i den här lösningen, PostgreSQL, ligger inte i Kubernetes alls.

## 10. När hade Kubernetes varit overkill för en lösning?

För precis den här lösningen, som den ser ut nu.

Tre simulerade sensorer som skickar tre mätvärden var femte sekund är ingen
last. En ensam container klarar det utan att anstränga sig. Docker Compose
startar hela miljön inklusive databas och cache med ett kommando, medan
Kubernetes-demon krävde att jag startade Minikube, byggde imagen in i klustret,
la på två manifest och sedan använde port-forward eller `minikube service` bara
för att nå sidan. Mer arbete, ingen vinst.

Det syns också på vad demon inte kunde göra. PostgreSQL och Redis ingår inte, så
i klustret fungerar bara `/health` och startsidan. De databasberoende
endpointerna hade krävt StatefulSets, PersistentVolumeClaims och Services för
databasen. Det är en rejäl mängd konfiguration för något Compose löser med fyra
rader.

Mer allmänt hade jag inte valt Kubernetes för en tjänst som körs på en server,
inte behöver skala, tål några minuters avbrott vid en uppdatering och sköts av
en person. Då blir Kubernetes mest en till sak att kunna och underhålla.

Det som skulle ändra saken är om lösningen behövde köra i flera repliker för att
klara lasten, uppdateras utan avbrott, starta om sig själv när något dör eller
köra på flera maskiner. Det är då man får tillbaka något för komplexiteten. I
labben såg jag exakt de sakerna fungera, men på en last som inte krävde dem.
