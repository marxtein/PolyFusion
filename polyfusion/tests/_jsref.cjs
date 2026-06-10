// ========== 物理常数 ==========
const qe = 1.6022e-19;    // 电子电荷 (C)
const mp = 1.6726e-27;    // 质子质量 (kg)
const mu0 = 4e-7 * Math.PI; // 真空磁导率 (H/m)
const mec2 = 511;         // 电子静质能 (keV)

// ========== 辅助数学函数 ==========
const linspace = (start, stop, num) => {
    const step = (stop - start) / (num - 1);
    return Array.from({length: num}, (_, i) => start + i * step);
};

// Gamma函数（Lanczos近似）
function logGamma(z) {
    const g = 7;
    const p = [0.99999999999980993, 676.5203681218851, -1259.1392167224028, 
               771.32342877765313, -176.61502916214059, 12.507343278686905, 
               -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7];
    if (z < 0.5) return Math.PI / (Math.sin(Math.PI * z) * Math.exp(logGamma(1 - z)));
    z -= 1;
    let x = p[0];
    for (let i = 1; i < g + 2; i++) x += p[i] / (z + i);
    const t = z + g + 0.5;
    return Math.log(Math.sqrt(2 * Math.PI)) + (z + 0.5) * Math.log(t) - t + Math.log(x);
}
const gamma = z => Math.exp(logGamma(z));

// ========== 反应截面函数 ==========

// D-T反应截面 (fsgmdt.m)
const fsgmdt = E_in => E_in.map(e => {
    if (e <= 0) return NaN;
    const BGdt = 34.3827; 
    let Sdt;
    if (e < 550) {
        const num = 6.927e4 + 7.454e8*e + 2.05e6*e**2 + 5.2002e4*e**3;
        const den = 1.0 + 6.38e1*e - 9.95e-1*e**2 + 6.981e-5*e**3 + 1.728e-4*e**4;
        Sdt = num / den;
    } else if (e <= 4700) {
        const den = 1.0 - 8.4127e-3*e + 4.7983e-6*e**2 - 1.0748e-9*e**3 + 8.85184e-14*e**4;
        Sdt = -1.4714e6 / den;
    } else { 
        return NaN; 
    }
    return Sdt / (e * Math.exp(BGdt / Math.sqrt(e))) * 1e-31;  // 修正：使用1e-31与MATLAB一致
});

// D-D反应截面总和 (fsgmdd1.m + fsgmdd2.m)
const fsgmdd_total = E_in => E_in.map(e => {
    if (e <= 0 || e > 4900) return NaN;
    const BGdd = 31.3970;
    const Sdd1 = 5.5576e4 + 2.1054e2*e - 3.2638e-2*e**2 + 1.4987e-6*e**3 + 1.8181e-10*e**4;
    const Sdd2 = 5.3701e4 + 3.3027e2*e - 1.2706e-1*e**2 + 2.9327e-5*e**3 - 2.5151e-9*e**4;
    return (Sdd1 + Sdd2) / (e * Math.exp(BGdd / Math.sqrt(e))) * 1e-31;  // 修正：使用1e-31与MATLAB一致
});

// D-He3反应截面 (fsgmdhe.m)
const fsgmdhe = E_in => E_in.map(e => {
    if (e <= 0) return NaN;
    const BGdhe = 68.7508; 
    let Sdhe;
    if (e < 900) {
        const num = 5.7501e6 + 2.5226e3*e + 4.5566e1*e**2;
        const den = 1.0 - 3.1995e-3*e - 8.5530e-6*e**2 + 5.9014e-8*e**3;
        Sdhe = num / den;
    } else if (e <= 4800) {
        const den = 1.0 - 2.6830e-3*e + 1.1633e-6*e**2 - 2.1332e-10*e**3 + 1.4250e-14*e**4;
        Sdhe = -8.3993e5 / den;
    } else { 
        return NaN; 
    }
    return Sdhe / (e * Math.exp(BGdhe / Math.sqrt(e))) * 1e-31;  // 修正：使用1e-31与MATLAB一致
});

// p-B11反应截面 (fsgmpb.m) - Nevins数据
const fsgmpb = E_in => E_in.map(e => {
    if (e < 0.5 || e > 3500) return NaN;
    const BGpb = 148.9596; // sqrt(22.589e3)
    let Spb;
    if (e <= 400) {
        Spb = 1.97e5 + 0.24e3 * e + 2.31e-1 * e**2 + 1.82e7 / ((e - 148)**2 + 2.35**2);
    } else if (e <= 642) {
        const E2 = e / 100 - 4; // 特殊变换
        Spb = 3.30e5 + 66.1e3 * E2 - 20.3e3 * E2**2 - 1.58e3 * E2**5;
    } else {
        Spb = 4.38e3 + 2.57e9 / ((e - 581.3)**2 + 85.7**2) + 5.67e8 / ((e - 1083)**2 + 234**2) +
              1.34e8 / ((e - 2405)**2 + 138**2) + 5.68e8 / ((e - 3344)**2 + 309**2);
    }
    return Spb / e * Math.exp(-BGpb / Math.sqrt(e)) * 1e-28; // 与MATLAB一致（p-B11使用1e-28）
});

// p-B11反应截面 (fsgmpb2.m) - Sikora数据
const fsgmpb2 = E_in => {
    const pBweller = [
        [140.8,0.006],[207.6,0.035],[237.0,0.057],[277.1,0.129],[370.7,0.390],
        [453.5,0.725],[528.4,1.194],[600.6,1.396],[670.1,1.145],[734.2,0.720],
        [803.7,0.463],[865.2,0.331],[913.3,0.316],[993.5,0.304],[1103.1,0.318],
        [1191.3,0.329],[1284.9,0.339],[1375.8,0.324],[1466.7,0.300],[1557.6,0.273],
        [1651.1,0.249],[1742.0,0.245],[1832.9,0.247],[1923.8,0.269],[2014.7,0.312],
        [2108.2,0.371],[2199.1,0.480],[2292.7,0.596],[2380.9,0.702],[2474.4,0.608],
        [2565.3,0.443],[2656.2,0.341],[2747.1,0.351],[2840.7,0.402],[2931.6,0.455],
        [3022.4,0.535],[3116.0,0.596],[3206.9,0.651],[3297.8,0.684],[3388.7,0.686],
        [3482.2,0.651]
    ];
    const dat_x = pBweller.map(p => p[0]); 
    const dat_y = pBweller.map(p => p[1]);
    
    function interp1(xi) {
        if (xi < dat_x[0] || xi > dat_x[dat_x.length - 1]) return NaN;
        const i = dat_x.findIndex(val => val >= xi); 
        if (i === 0) return dat_y[0];
        const [x0, y0] = [dat_x[i - 1], dat_y[i - 1]]; 
        const [x1, y1] = [dat_x[i], dat_y[i]];
        return y0 + (y1 - y0) * (xi - x0) / (x1 - x0);
    }
    
    return E_in.map(e => {
        if (e < 200) return fsgmpb([e])[0]; // 低能量时使用Nevins数据
        return interp1(e) * 1e-28; // mb转换为m^2（与MATLAB一致）
    });
};

// ========== 反应率计算 (fsgmv.m) ==========
const sgmv_cache = new Map();

function fsgmv(Teff, icase) {
    if (Teff <= 0) return 0;
    const cacheKey = `${Teff.toPrecision(4)}_${icase}`;
    if (sgmv_cache.has(cacheKey)) return sgmv_cache.get(cacheKey);
    
    const md = 2*mp, mt = 3*mp, mhe = 3*mp, mb = 11*mp;
    let sigma_func, Mr;
    
    switch (icase) {
        case 1: sigma_func = fsgmdt; Mr = (md * mt) / (md + mt); break;
        case 2: sigma_func = fsgmdd_total; Mr = (md * md) / (md + md); break;
        case 3: sigma_func = fsgmdhe; Mr = (md * mhe) / (md + mhe); break;
        case 4: sigma_func = fsgmpb; Mr = (mp * mb) / (mp + mb); break;
        case 5: sigma_func = fsgmpb2; Mr = (mp * mb) / (mp + mb); break;
        case 6: sigma_func = fsgmdd_total; Mr = (md * md) / (md + md); break;  // case 6 使用D-D截面
        default: return 0;
    }
    
    // 修正：使用与MATLAB一致的对数网格 E=10.^(-1:0.0005:3.6)
    const E_grid = [];
    for (let log_e = -1; log_e <= 3.6; log_e += 0.0005) {
        E_grid.push(Math.pow(10, log_e));
    }
    
    const sigma = sigma_func(E_grid);
    let integral = 0;
    
    // 修正：使用与MATLAB一致的积分方法（从E[2:end]开始，使用diff(E)）
    for (let i = 1; i < E_grid.length; i++) {
        if (!isNaN(sigma[i])) {
            const dE = E_grid[i] - E_grid[i-1];  // diff(E)
            integral += E_grid[i] * sigma[i] * dE * Math.exp(-E_grid[i] / Teff);
        }
    }
    
    // 修正：使用与MATLAB一致的前面系数
    const sgmv_val = Math.sqrt(qe*1e3*Teff*8/(Math.PI*Mr)) / (Teff**2) * integral;
    sgmv_cache.set(cacheKey, sgmv_val);
    return sgmv_val;
}

// ========== 主物理计算函数 (funsc.m) ==========
function funsc(R0, A, kappa, delta, Sn, ST, ni0, Ti0, fT, fsig, f1, BT0, Ip, tauE, fHe, fimp, Zimp, Rw, g, icase) {
    // 几何参数
    const a = R0 / A;
    const Ad = R0 / (g + a);  // 修正：添加Ad计算
    const Vp = (2*Math.PI**2*kappa*(A-delta) + 16*Math.PI*kappa*delta/3) * a**3;
    const Sp = (4*Math.PI**2*A*kappa**0.65 - 4*kappa*delta) * a**2;
    const Sw = (4*Math.PI**2*Ad*kappa**0.65 - 4*kappa*delta) * (a+g)**2;  // 修正：添加Sw计算
    
    // 温度和密度
    const Te0 = fT * Ti0;
    const f12 = 1.0 - fHe - fimp;
    const n120 = f12 * ni0;
    
    // 剖面积分 - 修正：与MATLAB完全一致，不需要乘以dx
    const x_grid = linspace(0, 1, 101);  // 对应MATLAB的x=0:0.01:1.0
    const dx = x_grid[1] - x_grid[0];
    let fTavg_num = 0, fnavg_num = 0, sum_x = 0;
    x_grid.forEach(x => { 
        fTavg_num += x*(1-x**2)**ST; 
        fnavg_num += x*(1-x**2)**Sn; 
        sum_x += x; 
    });
    const fTavg = fTavg_num / sum_x; 
    const fnavg = fnavg_num / sum_x;

    // 反应率积分 - 修正为与MATLAB一致的积分方式
    let phi_integrand = 0;
    for(let i = 0; i < x_grid.length; ++i) {
        const x = x_grid[i];
        const Tx = Ti0 * (1 - x**2)**ST;
        const sgv = fsgmv(Tx, icase);
        if(!isNaN(sgv)) {
            phi_integrand += (1 - x**2)**(2*Sn) * sgv * x * dx;  // 使用已定义的dx
        }
    }
    const Phi = fsig * 2 * phi_integrand;

    // 反应参数
    let Z1, Z2, A1, A2, fion, Y, M, delta12, x1, x2, strcase;
    switch(icase) {
        case 1: // D-T
            [Z1,Z2,A1,A2,fion,Y,delta12,x1,x2,strcase] = [1,1,2,3, 0.2, 17.59e6*qe, 0, f1, 1-f1, 'D-T']; 
            break;
        case 2: // D-D
            [Z1,Z2,A1,A2,fion,Y,delta12,x1,x2,strcase] = [1,1,2,2, (3.27/4+4.04)/(3.27+4.04), 0.5*(3.27+4.04)*1e6*qe, 1, 1, 1, 'D-D'];  // 修正：使用与MATLAB一致的fion和Y计算 
            break;
        case 3: // D-He3
            [Z1,Z2,A1,A2,fion,Y,delta12,x1,x2,strcase] = [1,2,2,3, 1.0, 18.35e6*qe, 0, f1, 1-f1, 'D-He3']; 
            break;
        case 4: // p-B11 Nevins
        case 5: // p-B11 Sikora
            [Z1,Z2,A1,A2,fion,Y,delta12,x1,x2,strcase] = [1,5,1,11, 1.0, 8.68e6*qe, 0, f1, 1-f1, icase===4 ? 'pB-Nevins' : 'pB-Sikora'];
            break;
        case 6: // D-D (cat) - 按照MATLAB代码中的case 6处理
            [Z1,Z2,A1,A2,fion,Y,delta12,x1,x2,strcase] = [1,1,2,2, 26.73/43.25, 0.5*43.25*1e6*qe, 1, 1, 1, 'D-D(cat)']; 
            break;
        default: 
            return {};
    }
    
    M = (x1*A1 + x2*A2) / (1 + delta12);
    const n10 = x1 * n120; 
    const n20 = x2 * n120; 
    const nHe0 = fHe * ni0; 
    const nimp0 = fimp * ni0;
    const ne0 = (n10*Z1 + n20*Z2)/(1+delta12) + nHe0*2 + nimp0*Zimp;
    const Zeff = ((n10*Z1**2 + n20*Z2**2)/(1+delta12) + nHe0*2**2 + nimp0*Zimp**2) / ne0;
    
    // 聚变功率
    const Pfus = Y / (1+delta12) * n10 * n20 * Phi * Vp * 1e-6;
    const Pn = Pfus * (1 - fion);
    
    // 轫致辐射功率
    const term1 = Zeff * (1/(1+2*Sn+0.5*ST));
    const term2 = 0.7936/(1+2*Sn+1.5*ST)*(Te0/mec2);
    const term3 = 1.874/(1+2*Sn+2.5*ST)*(Te0/mec2)**2;
    const term4_relativistic = 3/Math.sqrt(2)/(1+2*Sn+1.5*ST)*(Te0/mec2);
    const Pbrem = 5.34e-37*ne0**2*Math.sqrt(Te0)*(term1+term2+term3+term4_relativistic)*1e-6*Vp;

    // 回旋辐射功率
    const neff = ne0 / 1e20 / (1+Sn);  // 修正：添加除以1e20的步骤，与MATLAB一致
    const aeff = a * Math.sqrt(kappa); 
    // 修正：与MATLAB一致的有效温度计算 Teff=Te0*nansum((1-x.^2).^ST)*dx
    let Teff_integral = 0;
    x_grid.forEach(x => {
        Teff_integral += (1-x**2)**ST * dx;  // 使用已定义的dx
    });
    const Teff = Te0 * Teff_integral;
    const Pcycl = 4.14e-7 * (neff/1e0)**0.5 * Teff**2.5 * BT0**2.5 * (1-Rw)**0.5 * aeff**-0.5 * (1+2.5*Teff/511) * Vp * 1e0;  // 修正：使用1e0而非1e20，并添加1e0系数，与MATLAB一致

    // 能量约束
    const Eth = 1.5*(ni0*Ti0 + ne0*Te0)*1e3*qe/(1+Sn+ST)*Vp * 1e-6;
    const Pth = Eth / tauE; // MW（虽然MATLAB注释说是W，但实际应该是MW：Eth[MJ]/tauE[s]=MW）
    
    // 加热功率和增益因子
    const Pheat = Pcycl + Pbrem + Pth - fion*Pfus;
    let Qfus = (Pheat > 0) ? Pfus / Pheat : 1000;
    if (Qfus <= 0 || Qfus > 1000) Qfus = 1000;

    // β参数
    const betaT = 2*mu0*(ni0*Ti0 + ne0*Te0)*1e3*qe / (BT0**2) / (1+Sn+ST);
    const betaN = 100 * betaT / (Ip / (a * BT0));
    
    // 密度相关参数
    const nbar = ne0 * Math.sqrt(Math.PI)/2 * gamma(Sn+1)/gamma(Sn+1.5);
    const nGw = 1e20 * Ip / (Math.PI * a**2);
    const nbar_o_nGw = nbar / nGw;
    
    // 约束标度律
    const PLx = fion * Pfus + Pheat;
    const tauEIPB98x = (PLx > 0) ? 0.145*(Ip**0.93*R0**1.39*a**0.58*kappa**0.78*(nbar/1e20)**0.41*BT0**0.15*M**0.19)/PLx**0.69 : Infinity;
    const H98 = tauE / tauEIPB98x;
    const tauESTx = (PLx > 0) ? 0.066*(Ip**0.53*BT0**1.05*(nbar/1e19)**0.65*R0**2.66*kappa**0.78)/PLx**0.58 : Infinity;
    const HST = tauE / tauESTx;
    
    // 其他参数
    const q = 5*BT0*a**2*kappa/(R0*Ip);
    const Pwall = (Pfus + Pheat) / Sw;  // 修正：使用Sw而不是Sp，与MATLAB一致
    const betap = (25/betaT)*((1+kappa**2)/2)*(betaN/100)**2;

    return {
        Eth, H98, HST, Pheat, Pn, Pfus, Pwall, Qfus, betaN, betaT, nbar_o_nGw, q, 
        Pbrem, Pcycl, Vp, betap, Sp, ne0, M, fTavg, fnavg, strcase, Pth, Zeff, Sw  // 修正：添加Sw返回值
    };
}
module.exports={funsc,fsgmv,fsgmdt,fsgmdd_total,fsgmdhe,fsgmpb,fsgmpb2};
