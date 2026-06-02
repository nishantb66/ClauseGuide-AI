/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        midnight: "#08111f",
        glass: "#10243b",
        signal: "#d94f00",
        lime: "#80ef80"
      },
      boxShadow: {
        float: "0 10px 30px rgba(0, 0, 0, 0.28)",
      },
      fontFamily: {
        display: ["Avenir Next", "Avenir", "Segoe UI", "sans-serif"],
      },
    },
  },
  plugins: [],
};
