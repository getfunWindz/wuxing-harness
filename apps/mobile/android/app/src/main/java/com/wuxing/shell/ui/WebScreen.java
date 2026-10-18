package com.wuxing.shell.ui;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.net.Uri;
import android.view.LayoutInflater;
import android.view.View;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.TextView;

import com.wuxing.shell.R;
import com.wuxing.shell.bridge.WebBridge;
import com.wuxing.shell.connection.Connection;

/** WebView 承载屏：同源白名单 + 主框架错误层 + 重载/设置入口。 */
public final class WebScreen {
    public interface Listener {
        void onSettings();
    }

    private final Activity activity;
    private final View root;
    private final WebView webView;
    private final View errorPanel;
    private final TextView errorText;
    private Connection connection;

    public WebScreen(Activity activity, Listener listener) {
        this.activity = activity;
        root = LayoutInflater.from(activity).inflate(R.layout.screen_web, null, false);
        webView = root.findViewById(R.id.webview);
        errorPanel = root.findViewById(R.id.error_panel);
        errorText = root.findViewById(R.id.error_text);
        ((Button) root.findViewById(R.id.btn_retry)).setOnClickListener(v -> {
            errorPanel.setVisibility(View.GONE);
            reload();
        });
        ((Button) root.findViewById(R.id.btn_settings)).setOnClickListener(
                v -> listener.onSettings());
        configure(activity);
    }

    private void configure(Activity host) {
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setMediaPlaybackRequiresUserGesture(true);
        webView.addJavascriptInterface(new WebBridge(activity), "WuxingNative");
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                if (connection != null && connection.isInternal(uri.toString())) {
                    return false;
                }
                try {
                    host.startActivity(new Intent(Intent.ACTION_VIEW, uri));
                } catch (ActivityNotFoundException ignored) {
                    // 无外部应用可处理该链接：留在应用内阻断（白名单边界不变）
                }
                return true;
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request,
                                        WebResourceError error) {
                if (request.isForMainFrame()) {
                    showError(String.valueOf(error.getDescription()));
                }
            }
        });
    }

    public View root() {
        return root;
    }

    public WebView webView() {
        return webView;
    }

    public void load(Connection connection, String token) {
        this.connection = connection;
        errorPanel.setVisibility(View.GONE);
        webView.loadUrl(connection.connectUrl(token));
    }

    public void reload() {
        webView.reload();
    }

    public boolean canGoBack() {
        return webView.canGoBack();
    }

    public void goBack() {
        webView.goBack();
    }

    private void showError(String detail) {
        errorText.setText(activity.getString(R.string.error_connect) + "（" + detail + "）");
        errorPanel.setVisibility(View.VISIBLE);
    }
}
