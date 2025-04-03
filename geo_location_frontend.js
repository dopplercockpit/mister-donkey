export function useMyLocation(setCity) {
    if (!navigator.geolocation) {
      alert("Geolocation is not supported by your browser 😢");
      return;
    }
  
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const { latitude, longitude } = position.coords;
  
        fetch("/geo/reverse", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ lat: latitude, lon: longitude })
        })
          .then((res) => res.json())
          .then((data) => {
            if (data.city) {
              setCity(data.city); // use this to update app state
            } else {
              alert("Could not determine your city 😞");
            }
          });
      },
      (error) => {
        alert("Failed to get your location ❌");
        console.error(error);
      }
    );
  }
  