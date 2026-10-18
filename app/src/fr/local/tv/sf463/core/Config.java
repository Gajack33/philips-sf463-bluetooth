package fr.local.tv.sf463.core;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/** Portable, dependency-free configuration model. No Android objects or device IDs are persisted. */
public final class Config {
    public static final int SCHEMA = 1;
    public static final int LONG_MS = 600, DOUBLE_MS = 300;
    public String activeProfileId;
    public final List<Profile> profiles = new ArrayList<>();

    public static final class Action {
        public final String type, packageName;
        public Action(String type, String packageName) {
            if (!SetNames.ACTIONS.contains(type)) throw new IllegalArgumentException("Unknown action: " + type);
            if ("app".equals(type)) {
                if (packageName == null || packageName.length() > 160 || !packageName.matches("[A-Za-z_][A-Za-z0-9_]*(\\.[A-Za-z_][A-Za-z0-9_]*)+"))
                    throw new IllegalArgumentException("Invalid application package");
            } else if (packageName != null && !packageName.isEmpty()) throw new IllegalArgumentException("Unexpected application package");
            this.type = type; this.packageName = "app".equals(type) ? packageName : "";
        }
        public static Action none() { return new Action("none", ""); }
        public boolean present() { return !"none".equals(type); }
        public String toString() { return "app".equals(type) ? packageName : type; }
    }

    private static final class SetNames {
        static final Set<String> ACTIONS = new HashSet<>();
        static { for (String x : new String[]{"none", "app", "hdmi1", "hdmi2", "couchy", "settings", "self"}) ACTIONS.add(x); }
    }

    public static final class Button {
        public final int keyCode, scanCode, vendorId, productId;
        public final String label;
        public Button(int keyCode, int scanCode, int vendorId, int productId, String label) {
            if (keyCode < 1 || keyCode > 1023 || protectedKey(keyCode)) throw new IllegalArgumentException("Essential or invalid key: " + keyCode);
            if (scanCode < -1 || scanCode > 65535 || vendorId < 0 || vendorId > 65535 || productId < 0 || productId > 65535)
                throw new IllegalArgumentException("Invalid button identity");
            if (label == null || label.trim().isEmpty() || label.length() > 80) throw new IllegalArgumentException("Invalid button label");
            this.keyCode = keyCode; this.scanCode = scanCode; this.vendorId = vendorId; this.productId = productId; this.label = label.trim();
        }
        public boolean matches(int key, int scan, int vendor, int product) {
            return keyCode == key && (scanCode == -1 || scanCode == scan)
                && (vendorId == 0 || vendorId == vendor) && (productId == 0 || productId == product);
        }
        public int specificity() { return (scanCode >= 0 ? 4 : 0) + (vendorId != 0 ? 2 : 0) + (productId != 0 ? 1 : 0); }
        public String identity() { return keyCode + ":" + scanCode + ":" + vendorId + ":" + productId; }
    }

    public static final class Binding {
        public final Button button;
        public Action shortAction, longAction, doubleAction;
        public Binding(Button button, Action shortAction, Action longAction, Action doubleAction) {
            if (button == null || shortAction == null || longAction == null || doubleAction == null) throw new IllegalArgumentException("Incomplete binding");
            this.button = button; this.shortAction = shortAction; this.longAction = longAction; this.doubleAction = doubleAction;
        }
        public boolean enabled() { return shortAction.present() || longAction.present() || doubleAction.present(); }
    }

    public static final class Profile {
        public final String id;
        public String name;
        public boolean enabled;
        public final List<Binding> bindings = new ArrayList<>();
        public Profile(String id, String name, boolean enabled) {
            if (id == null || !id.matches("[A-Za-z0-9_-]{1,50}") || name == null || name.trim().isEmpty() || name.length() > 40)
                throw new IllegalArgumentException("Invalid profile identity");
            this.id = id; this.name = name.trim(); this.enabled = enabled;
        }
        public Binding find(int key, int scan, int vendor, int product) {
            Binding best = null;
            for (Binding b : bindings) if (b.button.matches(key, scan, vendor, product) && (best == null || b.button.specificity() > best.button.specificity())) best = b;
            return best;
        }
        public Profile copy(String newId, String newName) {
            Profile p = new Profile(newId, newName, false);
            for (Binding b : bindings) p.bindings.add(new Binding(b.button, b.shortAction, b.longAction, b.doubleAction));
            return p;
        }
    }

    public Profile active() {
        for (Profile p : profiles) if (p.id.equals(activeProfileId)) return p;
        throw new IllegalArgumentException("Active profile does not exist");
    }
    public void validate() {
        if (profiles.isEmpty() || profiles.size() > 16) throw new IllegalArgumentException("Keep 1 to 16 profiles");
        Set<String> ids = new HashSet<>();
        for (Profile p : profiles) {
            if (!ids.add(p.id) || p.bindings.size() > 32) throw new IllegalArgumentException("Duplicate profile or too many buttons");
            Set<String> keys = new HashSet<>();
            for (Binding b : p.bindings) if (!keys.add(b.button.identity())) throw new IllegalArgumentException("Duplicate button in profile");
        }
        active();
    }
    public void disableAll() { for (Profile p : profiles) p.enabled = false; }
    public static Config defaults() {
        Config c = new Config(); c.activeProfileId = "default";
        Profile p = new Profile("default", "Default", false);
        int[] keys = {183, 184, 185, 186};
        String[] names = {"Red", "Green", "Yellow", "Blue"};
        Action[] actions = {new Action("app", "com.movix.tv"), new Action("hdmi1", ""), new Action("hdmi2", ""), new Action("self", "")};
        for (int i = 0; i < keys.length; i++) p.bindings.add(new Binding(new Button(keys[i], -1, 0, 0, names[i]), actions[i], Action.none(), Action.none()));
        c.profiles.add(p); return c;
    }
    public static boolean protectedKey(int key) {
        switch (key) {
            case 0: case 3: case 4: case 19: case 20: case 21: case 22: case 23: case 24: case 25: case 26:
            case 66: case 84: case 91: case 164: case 177: case 219: case 223: case 224: case 225: case 231:
            case 268: case 269: case 270: case 271: case 276: return true;
            default: return false;
        }
    }
}
