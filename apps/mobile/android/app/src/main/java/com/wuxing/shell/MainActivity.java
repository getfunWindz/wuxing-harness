package com.wuxing.shell;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.view.Menu;
import android.view.MenuItem;
import android.webkit.WebSettings;
import android.widget.FrameLayout;

import com.wuxing.shell.connection.Connection;
import com.wuxing.shell.secure.TokenVault;
import com.wuxing.shell.ui.ConfigScreen;
import com.wuxing.shell.ui.WebScreen;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** WUXING Android 薄壳：配置 → WebView（同源白名单/错误层）→ 菜单与返回。 */
public class MainActivity extends Activity {
    private static final String PREFS = "wuxing.connection";
    private static final String KEY_URL = "url";
    private static final Pattern CHROME = Pattern.compile("Chrome/(\\d+)");

    private FrameLayout root;
    private ConfigScreen configScreen;
    private WebScreen webScreen;
    private boolean webMode;
    private boolean versionChecked;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        root = new FrameLayout(this);
        setContentView(root);
        requestNotificationPermission();
        String savedUrl = getSharedPreferences(PREFS, MODE_PRIVATE).getString(KEY_URL, "");
        Connection parsed = Connection.parse(savedUrl);
        String savedToken = safeLoadToken();
        if (parsed != null && savedToken != null && !savedToken.isEmpty()) {
            showWeb(parsed, savedToken);
        } else {
            showConfig();
        }
    }

    private String safeLoadToken() {
        try {
            return TokenVault.load(this);
        } catch (Exception e) {
            // Keystore 不可用（数据损坏/旧机）→ 当作无令牌；配置页提示重填
            return null;
        }
    }

    private void requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 1001);
        }
    }

    private void showConfig() {
        webMode = false;
        configScreen = new ConfigScreen(this, this::connect);
        configScreen.setUrl(getSharedPreferences(PREFS, MODE_PRIVATE)
                .getString(KEY_URL, ""));
        if (safeLoadToken() != null) {
            configScreen.setTokenHint(getString(R.string.token_saved_hint));
        }
        root.removeAllViews();
        root.addView(configScreen.root());
        invalidateOptionsMenu();
    }

    private void connect(String rawUrl, String rawToken) {
        Connection parsed = Connection.parse(rawUrl);
        if (parsed == null) {
            configScreen.setStatus(getString(R.string.error_url));
            return;
        }
        String useToken = rawToken == null ? "" : rawToken.trim();
        if (useToken.isEmpty()) {
            useToken = safeLoadToken();
        }
        if (useToken == null || useToken.isEmpty()) {
            configScreen.setStatus(getString(R.string.error_token));
            return;
        }
        try {
            TokenVault.save(this, useToken);
        } catch (Exception e) {
            configScreen.setStatus(getString(R.string.vault_unavailable)
                    + e.getClass().getSimpleName());
            return;
        }
        getSharedPreferences(PREFS, MODE_PRIVATE).edit()
                .putString(KEY_URL, parsed.baseUrl()).apply();
        showWeb(parsed, useToken);
    }

    private void showWeb(Connection parsed, String useToken) {
        webMode = true;
        if (webScreen == null) {
            webScreen = new WebScreen(this, this::showConfig);
        }
        root.removeAllViews();
        root.addView(webScreen.root());
        webScreen.load(parsed, useToken);
        invalidateOptionsMenu();
        if (!versionChecked) {
            versionChecked = true;
            checkWebViewVersion();
        }
    }

    private void checkWebViewVersion() {
        String userAgent = WebSettings.getDefaultUserAgent(this);
        Matcher matcher = CHROME.matcher(userAgent);
        if (!matcher.find()) {
            return;
        }
        int major = Integer.parseInt(matcher.group(1));
        if (major >= 105) {
            return;
        }
        new AlertDialog.Builder(this)
                .setTitle(R.string.webview_old_title)
                .setMessage(getString(R.string.webview_old_message, major))
                .setPositiveButton(R.string.continue_anyway, (dialog, which) -> {
                })
                .setNegativeButton(R.string.quit, (dialog, which) -> finish())
                .setCancelable(false)
                .show();
    }

    @Override
    public boolean onCreateOptionsMenu(Menu menu) {
        menu.add(0, 1, 0, R.string.menu_settings);
        menu.add(0, 2, 1, R.string.menu_reload);
        return true;
    }

    @Override
    public boolean onPrepareOptionsMenu(Menu menu) {
        menu.findItem(1).setVisible(webMode);
        menu.findItem(2).setVisible(webMode);
        return super.onPrepareOptionsMenu(menu);
    }

    @Override
    public boolean onOptionsItemSelected(MenuItem item) {
        if (item.getItemId() == 1) {
            showConfig();
            return true;
        }
        if (item.getItemId() == 2) {
            if (webScreen != null && webMode) {
                webScreen.reload();
            }
            return true;
        }
        return super.onOptionsItemSelected(item);
    }

    @Override
    public void onBackPressed() {
        if (webMode && webScreen != null && webScreen.canGoBack()) {
            webScreen.goBack();
            return;
        }
        moveTaskToBack(true);
    }
}
