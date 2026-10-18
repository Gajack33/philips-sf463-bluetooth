package fr.local.tv.sf463;

import android.content.Context;
import android.content.SharedPreferences;
import fr.local.tv.sf463.core.Config;
import fr.local.tv.sf463.core.JsonCodec;

final class Store {
    static final String NAME="sf463_profiles", KEY="configuration_v1";
    static SharedPreferences preferences(Context c) {return c.getSharedPreferences(NAME,Context.MODE_PRIVATE);}
    static Config load(Context c) {
        String text=preferences(c).getString(KEY,null);
        if(text==null) return Config.defaults();
        try {return JsonCodec.decode(text,false);} catch(IllegalArgumentException failure) {
            android.util.Log.e("SF463","Invalid saved profiles; shortcuts disabled",failure); return Config.defaults();
        }
    }
    static void save(Context c,Config model) {preferences(c).edit().putString(KEY,JsonCodec.encode(model)).apply();}
}
