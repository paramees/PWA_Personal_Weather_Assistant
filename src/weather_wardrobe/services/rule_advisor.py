from __future__ import annotations

from weather_wardrobe.models import DayWeatherSummary, OutfitAdvice, UserProfile


def _fmt_temp(value: float) -> str:
    rounded = int(round(value))
    if rounded > 0:
        return f"+{rounded}°"
    return f"{rounded}°"


class RuleBasedAdvisor:
    """Zero-dependency deterministic outfit advisor based on apparent temp and weather alerts."""

    def advise(
        self,
        summary: DayWeatherSummary,
        user: UserProfile,
    ) -> OutfitAdvice:
        eff_avg = summary.feels_avg + user.comfort_offset
        eff_min = summary.feels_min + user.comfort_offset
        alerts = summary.alerts
        any_rain = alerts.umbrella_required
        any_wind = alerts.strong_wind

        if eff_avg <= -10:
            headline = "Морозно — утепляйся по максимуму"
            top = "Термобельё (верх) + тёплый шерстяной свитер или плотный флис"
            outerwear = "Тёплый зимний пуховик или парка с высоким воротом"
            bottom = "Термобельё (низ) + плотные джинсы или утеплённые брюки"
            footwear = "Зимние утеплённые ботинки на толстой нескользящей подошве"
        elif eff_avg <= 0:
            headline = "Зимний холод — нужен тёплый верх"
            top = "Футболка или лонгслив + тёплый свитер или худи с начёсом"
            outerwear = "Зимняя куртка или пуховик"
            bottom = "Плотные джинсы или брюки (при ветре можно поддеть термоштаны)"
            footwear = "Утеплённые ботинки с протектором"
        elif eff_avg <= 7:
            headline = "Прохладно и зябко — одевайся в демисезон"
            top = "Лонгслив или рубашка + свитер или плотная толстовка"
            outerwear = "Утеплённая демисезонная куртка или плотное пальто"
            bottom = "Джинсы или плотные брюки чинос"
            footwear = "Демисезонные ботинки или утеплённые кожаные кроссовки"
        elif eff_avg <= 13:
            headline = "Свежо — пригодится лёгкая куртка и второй слой"
            top = "Футболка + свитшот, кардиган или лёгкий худи"
            outerwear = "Ветровка, тренч, бомбер или кожаная куртка"
            bottom = "Джинсы или повседневные брюки"
            footwear = "Закрытые кожаные кроссовки или ботинки"
        elif eff_avg <= 18:
            headline = "Умеренно прохладно — комфортная многослойность"
            top = "Футболка или лонгслив + лёгкая кофта или рубашка нараспашку"
            outerwear = "Лёгкая ветровка или джинсовка (на утро и вечер)"
            bottom = "Джинсы, чиносы или лёгкие брюки"
            footwear = "Кроссовки или кеды"
        elif eff_avg <= 23:
            headline = "Комфортно и тепло"
            top = "Футболка или лёгкая рубашка"
            outerwear = (
                "Лёгкая кофта или джинсовка на прохладное утро и вечер"
                if eff_min < 15
                else "Днём не требуется (можно взять тонкую кофту на вечер)"
            )
            bottom = "Лёгкие джинсы, чиносы или тонкие брюки"
            footwear = "Лёгкие кроссовки или кеды"
        else:
            headline = "Жарко — выбирай дышащие ткани"
            top = "Свободная хлопковая или льняная футболка"
            outerwear = "Не нужна"
            bottom = "Шорты или лёгкие льняные/хлопковые брюки"
            footwear = "Дышащие кеды, летние кроссовки или сандалии"

        accessories: list[str] = []

        if any_rain:
            rain_label = f" (дождь {alerts.rain_window})" if alerts.rain_window else ""
            accessories.append(f"☂️ Зонт{rain_label}")

            if eff_avg > 23:
                footwear = "Лёгкие непромокаемые кроссовки (без замши и ткани)"
            else:
                footwear = f"{footwear} (непромокаемые, без замши — будут лужи)"
            if outerwear == "Не нужна":
                outerwear = "Тонкий компактный дождевик на время дождя"
            elif "ветровка" not in outerwear.lower() and "дождевик" not in outerwear.lower():
                outerwear = f"{outerwear} (желательно с капюшоном или влагозащитой)"

        if alerts.snow_or_ice_risk:
            if "нескользящ" not in footwear and "протектор" not in footwear:
                footwear = f"{footwear} с цепким протектором (возможен снег/гололёд)"

        if any_wind:
            if outerwear == "Не нужна":
                outerwear = "Лёгкая ветровка от сильного ветра"
            elif "ветр" not in outerwear.lower():
                outerwear = f"{outerwear} (непродуваемая)"
            if eff_avg <= 13:
                accessories.append("🧣 Шарф или бафф от ветра")

        if eff_avg <= 0:
            accessories.extend(["🧶 Тёплая шапка", "🧤 Перчатки"])
            if not any("шарф" in item.lower() for item in accessories):
                accessories.append("🧣 Шарф")
        elif eff_avg <= 5:
            accessories.append("🧶 Лёгкая шапка на утро/вечер")

        if alerts.high_uv:
            accessories.append("🕶 Солнцезащитные очки и SPF-крем")

        if alerts.big_temp_swing:
            m_feels = _fmt_temp(summary.morning.apparent_temp)
            d_feels = _fmt_temp(summary.day.apparent_temp)
            e_feels = _fmt_temp(summary.evening.apparent_temp)
            pro_tip = (
                f"Перепад за день {alerts.temp_swing_delta:g}°C "
                f"(ощущ. утро {m_feels}, день {d_feels}, вечер {e_feels}) — "
                "одевайся слоями."
            )
        elif alerts.umbrella_required and alerts.rain_window:
            pro_tip = f"Дождь около {alerts.rain_window} — не забудь зонт перед выходом."
        elif alerts.strong_wind:
            pro_tip = (
                f"Ветер до {summary.max_wind_ms:.0f} м/с "
                f"(порывы до {summary.max_gusts_ms:.0f} м/с) — закрытый ворот решает."
            )
        elif alerts.heat_risk:
            pro_tip = "Жаркий день: бери воду с собой и выбирай светлые дышащие ткани."
        else:
            pro_tip = "Спокойная погода без сюрпризов — ориентируйся на базовые слои."

        return OutfitAdvice(
            headline=headline,
            top=top,
            outerwear=outerwear,
            bottom=bottom,
            footwear=footwear,
            accessories=accessories,
            pro_tip=pro_tip,
            source="rules",
            model_name=None,
        )
